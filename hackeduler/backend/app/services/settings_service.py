"""Admin-configurable application settings stored in ``application_settings``.

Secrets (SMTP password, JWT key) are intentionally NOT settings - they are env-only.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import ApplicationSetting

DEFAULTS: dict[str, tuple[Any, str]] = {
    "timezone": ("Asia/Kolkata", "Organisation timezone used for 'today' and working-day calculations"),
    "working_weekdays": ([0, 1, 2, 3, 4], "Working weekdays (0=Monday ... 6=Sunday)"),
    "pending_expiry_enabled": (True, "Automatically expire pending requests that are not reviewed in time"),
    "pending_expiry_hours": (72, "Hours a pending request holds its reservation before expiring"),
    "requester_direct_cancel_pending": (True, "Requesters may cancel their own PENDING bookings without admin approval"),
    "email_sender_name": ("Hackeduler", "Display name of the notification sender"),
    "email_sender_address": ("hackeduler@example.com", "From address for notifications"),
    "admin_notification_recipients": (["offsec-admins@example.com"], "Recipients of new-request / change-request emails"),
    "notify_requester_copy": (True, "Also send POC notifications to the requester when different from the POC"),
    "local_login_mode": ("all", "Local password sign-in: all | admins_only (break-glass) | disabled (SSO only)"),
    "public_base_url": (None, "Public URL of the app used to build SSO redirect URIs (null = HACKEDULER_APP_BASE_URL)"),
    "sso_auto_redirect": (False, "Send users straight to the only enabled SSO provider when local login is disabled"),
    "smtp_host": (None, "SMTP host override (null = use HACKEDULER_SMTP_HOST env)"),
    "smtp_port": (None, "SMTP port override (null = use HACKEDULER_SMTP_PORT env)"),
    "smtp_username": (None, "SMTP username override (password is env-only: HACKEDULER_SMTP_PASSWORD)"),
    "smtp_starttls": (None, "SMTP STARTTLS override (null = env)"),
}

VALIDATORS = {
    "timezone": lambda v: isinstance(v, str) and _valid_tz(v),
    "working_weekdays": lambda v: isinstance(v, list) and len(v) > 0 and all(isinstance(i, int) and 0 <= i <= 6 for i in v),
    "pending_expiry_enabled": lambda v: isinstance(v, bool),
    "pending_expiry_hours": lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 24 * 90,
    "requester_direct_cancel_pending": lambda v: isinstance(v, bool),
    "email_sender_name": lambda v: isinstance(v, str) and 0 < len(v) <= 120 and "\n" not in v and "\r" not in v,
    "email_sender_address": lambda v: isinstance(v, str) and "@" in v and len(v) <= 254 and "\n" not in v,
    "admin_notification_recipients": lambda v: isinstance(v, list) and all(isinstance(e, str) and "@" in e and "\n" not in e for e in v),
    "notify_requester_copy": lambda v: isinstance(v, bool),
    "local_login_mode": lambda v: v in ("all", "admins_only", "disabled"),
    "public_base_url": lambda v: v is None or (isinstance(v, str) and v.startswith(("http://", "https://")) and len(v) <= 300 and "\n" not in v and " " not in v),
    "sso_auto_redirect": lambda v: isinstance(v, bool),
    "smtp_host": lambda v: v is None or (isinstance(v, str) and len(v) <= 255 and "\n" not in v),
    "smtp_port": lambda v: v is None or (isinstance(v, int) and 0 < v < 65536),
    "smtp_username": lambda v: v is None or (isinstance(v, str) and len(v) <= 255),
    "smtp_starttls": lambda v: v is None or isinstance(v, bool),
}


def _valid_tz(v: str) -> bool:
    try:
        ZoneInfo(v)
        return True
    except Exception:
        return False


def get_setting(db: Session, key: str) -> Any:
    row = db.get(ApplicationSetting, key)
    if row is None:
        return DEFAULTS[key][0]
    return row.value


def get_all(db: Session) -> dict[str, Any]:
    rows = {r.key: r.value for r in db.query(ApplicationSetting).all()}
    return {k: rows.get(k, default) for k, (default, _) in DEFAULTS.items()}


def set_setting(db: Session, key: str, value: Any, user_id=None) -> tuple[Any, Any]:
    if key not in DEFAULTS:
        raise KeyError(key)
    if not VALIDATORS[key](value):
        raise ValueError(f"Invalid value for setting '{key}'")
    row = db.get(ApplicationSetting, key)
    old = row.value if row else DEFAULTS[key][0]
    if row is None:
        row = ApplicationSetting(key=key, value=value, description=DEFAULTS[key][1], updated_by=user_id)
        db.add(row)
    else:
        row.value = value
        row.updated_by = user_id
    return old, value


def org_tz(db: Session) -> ZoneInfo:
    return ZoneInfo(get_setting(db, "timezone"))


def org_today(db: Session) -> date:
    return datetime.now(org_tz(db)).date()
