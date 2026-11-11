"""Activity initiation email: "send us what we need before testing starts".

When it goes out
  * automatically, N days before the booking's start date (global setting, optional per-activity override);
  * only for APPROVED bookings that have a start date, and only once per start date;
  * a booking approved late (already inside the window) is sent straight away;
  * a rescheduled booking is sent again ahead of its new date;
  * an administrator can always send it manually from the booking.

What it asks for depends on the activity type: admins can edit the checklist per activity type, otherwise a
built-in checklist chosen from the activity name (web, mobile, API, ...) is used.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActivityType, Booking, BookingStatus, User
from . import audit, notifications, settings_service
from .availability import now_utc

# --------------------------------------------------------------------------------------
# default checklists
# --------------------------------------------------------------------------------------
COMMON = [
    "Scope: what is in scope and what is explicitly out of scope",
    "IP whitelisting: confirm our testing source IPs are allowed through firewalls / WAF / IPS (we will share them on request)",
    "A technical contact who is available during the testing window",
    "Confirmation that the environment is stable, has realistic test data and that no release / change freeze clashes with the testing dates",
    "Any restrictions: testing hours, rate limits, fragile systems, data we must not touch",
]

CHECKLISTS: dict[str, tuple[str, list[str]]] = {
    "web": ("Web application", [
        "Application URL(s) of the environment to be tested (UAT / staging) and any related sub-domains",
        "Test accounts for every user role (admin, standard user, etc.). Share credentials through a secure channel, not by email",
        "Application walkthrough or user guide, and a list of key functionality / modules",
        "API documentation (Swagger / OpenAPI / Postman collection) if the application exposes APIs",
        "How to handle CAPTCHA, MFA / OTP and WAF or rate limiting for the test accounts",
    ]),
    "hybrid": ("Hybrid / code-assisted application", [
        "Application URL(s) of the environment to be tested and test accounts for every user role",
        "Read-only access to each in-scope code repository, with the branch / tag / commit to be reviewed",
        "Build and run instructions, architecture overview and the main technologies used",
        "Mobile builds (if the application has a mobile component) and the matching back-end environment",
    ]),
    "mobile": ("Mobile application", [
        "The build to be tested: APK / IPA, or TestFlight / Play Store internal-testing invitation, with the version number",
        "Platforms and minimum OS versions in scope (Android, iOS)",
        "Back-end / API URLs and the environment the build connects to",
        "Test accounts for every user role. Share credentials through a secure channel, not by email",
        "A build without root / jailbreak detection and SSL pinning, if possible (or tell us how these are enforced)",
    ]),
    "api": ("API", [
        "Base URL(s) of the environment to be tested",
        "API documentation: OpenAPI / Swagger file or Postman collection, including the number of endpoints in scope",
        "Authentication method and test credentials / tokens for every role, with sample requests",
        "Rate limits, throttling and any API gateway or WAF behaviour we should expect",
    ]),
    "thick": ("Thick client", [
        "Installer and version of the client, with installation instructions and OS requirements",
        "Back-end servers / services the client connects to (hosts, ports, protocols) and the environment they belong to",
        "Test accounts for every user role and any licence keys needed. Share credentials through a secure channel",
        "Architecture overview, including any local database, update mechanism or inter-process communication",
    ]),
    "network": ("Network / infrastructure", [
        "IP ranges, hostnames and VLANs in scope, and anything excluded",
        "VPN / jump-host access details for the testing machine and a network diagram if available",
        "Expected segmentation rules (which zones must not reach each other)",
        "Systems that are fragile or business critical, and the testing windows allowed for them",
    ]),
    "cloud": ("Cloud", [
        "Cloud provider, account / subscription / project IDs and regions in scope",
        "A read-only audit role / service principal for the review, and the process to receive its credentials securely",
        "Architecture overview and the list of services in use",
    ]),
    "llm": ("LLM / AI", [
        "Chat interface URL or model API endpoint, and the model(s) and version(s) in use",
        "Architecture overview: system prompt purpose, RAG data sources, tools / plug-ins / agents the model can call",
        "Test accounts for every user role, plus any usage limits or token budgets",
        "Existing guardrails / content filters and the sensitivity of the data the model can reach",
    ]),
    "scan": ("Automated scan", [
        "Target URL(s) / IP addresses to scan",
        "Authentication to use for an authenticated scan (test account) and any pages to avoid",
        "Allowed scanning window and the scanner source IPs that must be whitelisted",
    ]),
}

# name keyword -> checklist key (checked in this order; several can match, e.g. "Web Application PT with LLM")
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("scan", ("scan", "xbow", "automated")),
    ("hybrid", ("hybrid", "code review", "source code")),
    ("mobile", ("mobile", "android", "ios")),
    ("api", ("api",)),
    ("thick", ("thick client", "thick-client", "desktop")),
    ("network", ("network", "segmentation", "infrastructure", "wireless")),
    ("cloud", ("cloud", "aws", "azure", "gcp")),
    ("web", ("web",)),
    ("llm", ("llm", " ai ", "genai", "gen ai")),
]


def _words(name: str) -> str:
    return f" {name.lower().replace('-', ' ').replace('–', ' ').replace('/', ' ').replace('+', ' ')} "


def default_details(activity_name: str) -> str:
    """Built-in checklist for an activity name (a generic one when nothing matches)."""
    w = _words(activity_name or "")
    kinds = [k for k, words in KEYWORDS if any((f" {x} " if x in ("api", "ios", "aws", "gcp", "ai") else x) in w for x in words)]
    lines: list[str] = []
    if len(kinds) > 1:
        for k in kinds:
            title, items = CHECKLISTS[k]
            lines.append(f"{title}:")
            lines += [f"- {i}" for i in items]
            lines.append("")
        lines.append("For all of the above:")
    elif kinds:
        lines += [f"- {i}" for i in CHECKLISTS[kinds[0]][1]]
    else:
        lines += ["- The environment / URL(s) or build to be tested",
                  "- Test accounts for every user role. Share credentials through a secure channel, not by email"]
    lines += [f"- {c}" for c in COMMON]
    return "\n".join(lines)


def required_details(b: Booking) -> str:
    a: ActivityType | None = b.activity_type
    custom = (a.initiation_details or "").strip() if a else ""
    return custom or default_details(b.activity_name_snapshot)


# --------------------------------------------------------------------------------------
# schedule
# --------------------------------------------------------------------------------------

def days_before(db: Session, b: Booking) -> int:
    a = b.activity_type
    if a is not None and a.initiation_days_before is not None:
        return int(a.initiation_days_before)
    return int(settings_service.get_setting(db, "initiation_email_days_before"))


def automatic_enabled(db: Session, b: Booking) -> bool:
    """Automatic sending: global switch on AND not switched off for this activity type."""
    if not settings_service.get_setting(db, "initiation_email_enabled"):
        return False
    a = b.activity_type
    return bool(a is None or a.initiation_email_enabled)


def send_on(db: Session, b: Booking) -> date | None:
    return b.start_date - timedelta(days=days_before(db, b)) if b.start_date else None


def status(db: Session, b: Booking) -> dict[str, Any]:
    """What the admin sees on a booking: sent / scheduled / disabled / not applicable."""
    today = settings_service.org_today(db)
    info: dict[str, Any] = {"state": "not_applicable", "sent_at": b.initiation_email_sent_at,
                            "sent_for_start": b.initiation_email_for_start, "scheduled_for": None, "days_before": None,
                            "can_send": False}
    if b.status != BookingStatus.APPROVED or not b.start_date:
        info["note"] = ("Only approved bookings with a start date get this email."
                        if not b.initiation_email_sent_at else "")
        info["state"] = "sent" if b.initiation_email_sent_at else "not_applicable"
        return info
    info["can_send"] = True
    info["days_before"] = days_before(db, b)
    if b.initiation_email_for_start == b.start_date and b.initiation_email_sent_at:
        info["state"] = "sent"
    elif not automatic_enabled(db, b):
        info["state"] = "disabled"
    elif b.start_date < today:
        info["state"] = "not_applicable"
        info["note"] = "The start date has passed; use Send now if it is still needed."
    else:
        info["state"] = "scheduled"
        info["scheduled_for"] = max(send_on(db, b), today) if send_on(db, b) else None
    return info


def _days_text(db: Session, b: Booking) -> str:
    n = (b.start_date - settings_service.org_today(db)).days
    return "today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days" if n > 1 else f"{-n} day(s) ago"


def send(db: Session, b: Booking, actor: User | None = None, *, manual: bool = False) -> bool:
    """Queue the email to the POC (and the requester per the existing copy setting) and record it on the booking."""
    if b.status != BookingStatus.APPROVED or not b.start_date:
        return False
    ctx = notifications.booking_context(b, **{"Required Details": required_details(b), "Days Until Start": _days_text(db, b)})
    rows = notifications.enqueue(db, "activity_initiation_poc", notifications.poc_recipients(db, b), ctx, b.id)
    prev = {"sent_at": audit.jsonable(b.initiation_email_sent_at), "for_start": audit.jsonable(b.initiation_email_for_start)}
    b.initiation_email_sent_at = now_utc()
    b.initiation_email_for_start = b.start_date
    audit.record(db, "booking.initiation_email_sent", actor, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 previous=prev, new={"for_start": audit.jsonable(b.start_date), "manual": manual,
                                     "recipients": [r.recipient for r in rows]})
    return True


def is_due(db: Session, b: Booking) -> bool:
    if b.status != BookingStatus.APPROVED or not b.start_date:
        return False
    if b.initiation_email_for_start == b.start_date and b.initiation_email_sent_at:
        return False                      # once per start date
    if not automatic_enabled(db, b):
        return False
    today = settings_service.org_today(db)
    return b.start_date >= today and today >= send_on(db, b)


def send_if_due(db: Session, b: Booking) -> bool:
    """Called right after approval / reschedule so a booking already inside the window is sent immediately."""
    return send(db, b) if is_due(db, b) else False


def send_due(db: Session) -> int:
    """Worker pass: send every approved booking whose send date has arrived."""
    if not settings_service.get_setting(db, "initiation_email_enabled"):
        return 0
    today = settings_service.org_today(db)
    q = (select(Booking).where(Booking.status == BookingStatus.APPROVED, Booking.start_date.is_not(None),
                               Booking.start_date >= today,
                               (Booking.initiation_email_for_start.is_(None)) | (Booking.initiation_email_for_start != Booking.start_date))
         .with_for_update(of=Booking, skip_locked=True))
    n = 0
    for b in db.scalars(q).unique().all():
        if send_if_due(db, b):
            n += 1
    return n
