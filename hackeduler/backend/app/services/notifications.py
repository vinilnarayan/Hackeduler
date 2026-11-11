"""Email templates and the transactional outbox.

``enqueue_*`` functions only INSERT rows into ``email_notification_logs`` inside
the caller's transaction. Delivery happens later in the worker
(:mod:`app.services.email_sender`). Therefore:
  * a committed booking change always has its notification persisted, and
  * an SMTP failure can never roll back or corrupt a booking.

Templates use ``{{Variable Name}}`` placeholders. Substitution is a plain,
whitelist-based text replacement (no expression evaluation), and the output is
sent as text/plain, so template content cannot execute code or inject markup.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..models import Booking, BookingStatus, EmailNotificationLog, EmailTemplate
from . import settings_service

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9 _/\-]*?)\s*\}\}")

ALLOWED_VARIABLES = {
    "Booking ID", "Application Name", "Application Version", "Activity Type", "PCI DSS Scope", "Yes/No",
    "Resource ID", "Start Date", "End Date", "Duration", "POC Name", "POC Email", "Rejection Reason",
    "Booking Status", "Change Summary", "Reason", "Requester", "App URL", "Product", "Implementation",
    "User Name", "User Email", "Role", "Engineer Name", "Additional Comments",
}

SIGNATURE = "\n\nRegards,\nOffensive Security Team\n"

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "booking_submitted_admin": {
        "name": "New booking request (to admins)",
        "subject": "[Hackeduler] New Booking Request – {{Booking ID}}",
        "body": (
            "Hello Admin,\n\nA new security assessment booking request has been submitted.\n\n"
            "- Booking ID: {{Booking ID}}\n- Application Name: {{Application Name}}\n"
            "- Application Version: {{Application Version}}\n- Activity Type: {{Activity Type}}\n"
            "- PCI DSS Scope: {{Yes/No}}\n- Resource: {{Resource ID}}\n- Start Date: {{Start Date}}\n"
            "- Expected End Date: {{End Date}}\n- POC Name: {{POC Name}}\n- POC Email: {{POC Email}}\n\n"
            "Please log in to the Hackeduler to review and approve or reject this request."
            + SIGNATURE
        ),
    },
    "booking_approved_poc": {
        "name": "Booking approved (to POC)",
        "subject": "[Hackeduler] Booking Approved – {{Booking ID}}",
        "body": (
            "Hello {{POC Name}},\n\nYour security assessment booking request has been approved.\n\n"
            "- Booking ID: {{Booking ID}}\n- Application Name: {{Application Name}}\n"
            "- Application Version: {{Application Version}}\n- Activity Type: {{Activity Type}}\n"
            "- Start Date: {{Start Date}}\n- Expected End Date: {{End Date}}\n- Booking Status: Approved\n\n"
            "Please coordinate with the Offensive Security team for further arrangements." + SIGNATURE
        ),
    },
    "booking_rejected_poc": {
        "name": "Booking rejected (to POC)",
        "subject": "[Hackeduler] Booking Rejected – {{Booking ID}}",
        "body": (
            "Hello {{POC Name}},\n\nYour security assessment booking request has been reviewed but could not be approved.\n\n"
            "- Booking ID: {{Booking ID}}\n- Application Name: {{Application Name}}\n"
            "- Activity Type: {{Activity Type}}\n- Requested Start Date: {{Start Date}}\n- Booking Status: Rejected\n\n"
            "Reason for rejection:\n\n{{Rejection Reason}}\n\n"
            "Please contact the Offensive Security team if you need further clarification." + SIGNATURE
        ),
    },
    "booking_modified_poc": {
        "name": "Booking modified (to POC)",
        "subject": "[Hackeduler] Booking Updated – {{Booking ID}}",
        "body": (
            "Hello {{POC Name}},\n\nYour approved security assessment booking has been updated.\n\n"
            "- Booking ID: {{Booking ID}}\n- Application Name: {{Application Name}}\n"
            "- Application Version: {{Application Version}}\n- Activity Type: {{Activity Type}}\n"
            "- Resource: {{Resource ID}}\n- Start Date: {{Start Date}}\n- Expected End Date: {{End Date}}\n"
            "- Booking Status: {{Booking Status}}\n\nWhat changed:\n{{Change Summary}}\n\nReason:\n{{Reason}}\n\n"
            "Please contact the Offensive Security team if you have any questions." + SIGNATURE
        ),
    },
    "booking_cancelled_poc": {
        "name": "Booking cancelled (to POC)",
        "subject": "[Hackeduler] Booking Cancelled – {{Booking ID}}",
        "body": (
            "Hello {{POC Name}},\n\nThe following security assessment booking has been cancelled.\n\n"
            "- Booking ID: {{Booking ID}}\n- Application Name: {{Application Name}}\n"
            "- Activity Type: {{Activity Type}}\n- Start Date: {{Start Date}}\n- Booking Status: Cancelled\n\n"
            "Reason:\n{{Reason}}" + SIGNATURE
        ),
    },
    "booking_impacted_poc": {
        "name": "Booking impacted by an administrative change (to POC)",
        "subject": "[Hackeduler] Schedule Review Required – {{Booking ID}}",
        "body": (
            "Hello {{POC Name}},\n\nAn administrative scheduling change affects your approved booking. "
            "Your booking has NOT been moved or cancelled; the Offensive Security team will review it and contact you "
            "if any change is required.\n\n- Booking ID: {{Booking ID}}\n- Application Name: {{Application Name}}\n"
            "- Activity Type: {{Activity Type}}\n- Start Date: {{Start Date}}\n- Expected End Date: {{End Date}}\n\n"
            "Details:\n{{Change Summary}}" + SIGNATURE
        ),
    },
    "change_request_admin": {
        "name": "Cancellation / reschedule request (to admins)",
        "subject": "[Hackeduler] Change Request – {{Booking ID}}",
        "body": (
            "Hello Admin,\n\nA requester has asked to change a booking.\n\n- Booking ID: {{Booking ID}}\n"
            "- Application Name: {{Application Name}}\n- Requester: {{Requester}}\n- Request: {{Change Summary}}\n"
            "- Reason: {{Reason}}\n\nPlease review the request in the Hackeduler." + SIGNATURE
        ),
    },
    "change_request_declined": {
        "name": "Cancellation / reschedule request declined (to requester/POC)",
        "subject": "[Hackeduler] Change Request Declined – {{Booking ID}}",
        "body": (
            "Hello {{POC Name}},\n\n{{Change Summary}}\n\n- Booking ID: {{Booking ID}}\n"
            "- Application Name: {{Application Name}}\n- Start Date: {{Start Date}}\n- Expected End Date: {{End Date}}\n"
            "- Booking Status: {{Booking Status}}\n\nReason:\n{{Reason}}" + SIGNATURE
        ),
    },
    "booking_expired_requester": {
        "name": "Pending request expired (to requester/POC)",
        "subject": "[Hackeduler] Booking Request Expired – {{Booking ID}}",
        "body": (
            "Hello {{POC Name}},\n\nThe booking request below was not reviewed within the reservation period and has "
            "expired. The reserved slot has been released. Please submit a new request if the assessment is still required.\n\n"
            "- Booking ID: {{Booking ID}}\n- Application Name: {{Application Name}}\n- Activity Type: {{Activity Type}}\n"
            "- Requested Start Date: {{Start Date}}" + SIGNATURE
        ),
    },
    "user_welcome": {
        "name": "Welcome / account created (to new user)",
        "subject": "[Hackeduler] Your account is ready",
        "body": (
            "Hello {{User Name}},\n\nAn account has been created for you on Hackeduler, the Offensive Security "
            "scheduling portal.\n\n- Name: {{User Name}}\n- Email: {{User Email}}\n- Role: {{Role}}\n\n"
            "Sign in with your company single sign-on (SSO) account here:\n{{App URL}}\n\n"
            "Please contact the Offensive Security team if you have any trouble signing in." + SIGNATURE
        ),
    },
    "booking_confirmed_engineer": {
        "name": "Booking confirmed (to security engineer)",
        "subject": "[Hackeduler] Assignment Confirmed – {{Application Name}} ({{Start Date}})",
        "body": (
            "Hello {{Engineer Name}},\n\nYou have been assigned to the following confirmed security assessment.\n\n"
            "- Booking ID: {{Booking ID}}\n- Application Name: {{Application Name}}\n"
            "- Application Version: {{Application Version}}\n- Activity Type: {{Activity Type}}\n"
            "- PCI DSS Scope: {{Yes/No}}\n- Start Date: {{Start Date}}\n- Expected End Date: {{End Date}}\n"
            "- POC Name: {{POC Name}}\n- POC Email: {{POC Email}}\n\nAdditional comments:\n{{Additional Comments}}\n\n"
            "Details are available in Hackeduler: {{App URL}}" + SIGNATURE
        ),
    },
}


def template_variables(text: str) -> set[str]:
    return {m.group(1) for m in PLACEHOLDER_RE.finditer(text)}


def validate_template(subject: str, body: str) -> None:
    unknown = (template_variables(subject) | template_variables(body)) - ALLOWED_VARIABLES
    if unknown:
        raise ValueError(f"Unknown template variable(s): {', '.join(sorted(unknown))}")
    if "\n" in subject or "\r" in subject:
        raise ValueError("Subject must be a single line")


def render(text: str, ctx: dict[str, Any]) -> str:
    return PLACEHOLDER_RE.sub(lambda m: str(ctx.get(m.group(1), "")), text)


def booking_context(b: Booking, **extra: Any) -> dict[str, Any]:
    from ..config import get_settings

    yes_no = "Yes" if b.pci_dss_scope else "No"
    ctx = {
        "Booking ID": str(b.id),
        "Application Name": b.application_name,
        "Application Version": b.application_version,
        "Activity Type": b.activity_name_snapshot,
        "PCI DSS Scope": yes_no,
        "Yes/No": yes_no,
        "Resource ID": b.resource.display_name if b.resource else "Not required",
        "Start Date": b.start_date.isoformat() if b.start_date else "To be scheduled",
        "End Date": b.end_date.isoformat() if b.end_date else "To be scheduled",
        "Duration": f"{b.duration_days} working days" if b.duration_days else "Not applicable",
        "Product": b.product.name if b.product else "",
        "Implementation": b.implementation.name if b.implementation else "",
        "POC Name": b.poc_name,
        "POC Email": b.poc_email,
        "Rejection Reason": b.rejection_reason or "",
        "Booking Status": BookingStatus.LABELS.get(b.status, b.status),
        "Requester": b.requester.full_name if b.requester else "",
        "App URL": get_settings().app_base_url,
        "Change Summary": "",
        "Reason": "",
    }
    ctx.update(extra)
    return ctx


def _get_template(db: Session, key: str) -> tuple[str, str] | None:
    t = db.query(EmailTemplate).filter_by(key=key).one_or_none()
    if t is not None:
        if not t.is_active:
            return None
        return t.subject_template, t.body_template
    d = DEFAULT_TEMPLATES[key]
    return d["subject"], d["body"]


def enqueue(db: Session, key: str, recipients: list[str], ctx: dict[str, Any], booking_id: uuid.UUID | None = None) -> list[EmailNotificationLog]:
    tpl = _get_template(db, key)
    if tpl is None:
        return []
    subject = render(tpl[0], ctx).replace("\r", " ").replace("\n", " ")[:300]
    body = render(tpl[1], ctx)
    rows = []
    seen = set()
    for r in recipients:
        r = (r or "").strip()
        if not r or r.lower() in seen:
            continue
        seen.add(r.lower())
        row = EmailNotificationLog(id=uuid.uuid4(), template_key=key, booking_id=booking_id, recipient=r, subject=subject, body=body)
        db.add(row)
        rows.append(row)
    return rows


def admin_recipients(db: Session) -> list[str]:
    return list(settings_service.get_setting(db, "admin_notification_recipients") or [])


def poc_recipients(db: Session, b: Booking) -> list[str]:
    rec = [b.poc_email]
    if settings_service.get_setting(db, "notify_requester_copy") and b.requester and b.source == "requester":
        rec.append(b.requester.email)
    return rec


def notify_submitted(db: Session, b: Booking) -> None:
    enqueue(db, "booking_submitted_admin", admin_recipients(db), booking_context(b), b.id)


def engineer_resources(b: Booking) -> list:
    """Every security resource working on the booking (primary first)."""
    out = [b.resource] if b.resource else []
    out += [r for r in getattr(b, "extra_resources", []) if r not in out]
    return out


def notify_engineers(db: Session, b: Booking) -> None:
    """Tell the assigned security engineer(s) a booking is confirmed. Engineers without an email are skipped."""
    for r in engineer_resources(b):
        if not r.engineer_email:
            continue
        ctx = booking_context(b, **{"Engineer Name": r.engineer_name or r.display_name,
                                    "Additional Comments": b.additional_comments or "None"})
        enqueue(db, "booking_confirmed_engineer", [r.engineer_email], ctx, b.id)


def notify_approved(db: Session, b: Booking) -> None:
    enqueue(db, "booking_approved_poc", poc_recipients(db, b), booking_context(b), b.id)
    notify_engineers(db, b)


def notify_user_welcome(db: Session, user) -> None:
    from .sso import public_base_url

    ctx = {"User Name": user.full_name, "User Email": user.email, "Role": "Administrator" if user.is_admin else "Requester",
           "App URL": public_base_url(db)}
    enqueue(db, "user_welcome", [user.email], ctx)


def notify_rejected(db: Session, b: Booking) -> None:
    enqueue(db, "booking_rejected_poc", poc_recipients(db, b), booking_context(b), b.id)


def notify_modified(db: Session, b: Booking, summary: str, reason: str) -> None:
    enqueue(db, "booking_modified_poc", poc_recipients(db, b), booking_context(b, **{"Change Summary": summary, "Reason": reason}), b.id)


def notify_cancelled(db: Session, b: Booking, reason: str) -> None:
    enqueue(db, "booking_cancelled_poc", poc_recipients(db, b), booking_context(b, Reason=reason), b.id)


def notify_impacted(db: Session, b: Booking, summary: str) -> None:
    enqueue(db, "booking_impacted_poc", poc_recipients(db, b), booking_context(b, **{"Change Summary": summary}), b.id)


def notify_change_request(db: Session, b: Booking, summary: str, reason: str) -> None:
    enqueue(db, "change_request_admin", admin_recipients(db), booking_context(b, **{"Change Summary": summary, "Reason": reason}), b.id)


def notify_expired(db: Session, b: Booking) -> None:
    enqueue(db, "booking_expired_requester", poc_recipients(db, b), booking_context(b), b.id)
