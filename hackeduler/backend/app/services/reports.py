"""Report-sharing on a booking: shared yes/no, which report (V1 or Met) and free-text comments.

Used by the assigned engineer (resource role) and by admins. Nothing else on the booking changes.
"""
from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..errors import bad_request
from ..models import Booking, BookingStatus, User
from . import audit
from .availability import now_utc

REPORT_TYPES = ("V1", "Met")
REPORTABLE = (BookingStatus.APPROVED, BookingStatus.COMPLETED)


def clean_url(value: str | None) -> str | None:
    """Report link: optional, but when given it must be an absolute https URL (no spaces, <= 2000 chars)."""
    v = (value or "").strip()
    if not v:
        return None
    parsed = urlparse(v)
    if parsed.scheme.lower() != "https" or not parsed.netloc or any(c.isspace() for c in v) or len(v) > 2000:
        raise bad_request("The report link must be a valid https:// URL (for example your SharePoint link).")
    return v


def set_report(db: Session, b: Booking, actor: User, *, shared: bool, report_type: str | None,
               comments: str | None, url: str | None = None, notify_poc: bool = False) -> Booking:
    if b.status not in REPORTABLE:
        raise bad_request("Report details can only be recorded on approved or completed bookings.")
    if report_type is not None and report_type not in REPORT_TYPES:
        raise bad_request("Report type must be V1 or Met.")
    if shared and not report_type:
        raise bad_request("Choose the report type (V1 or Met) when marking the report as shared.")
    comments = (comments or "").strip() or None
    url = clean_url(url)
    if shared and not url:
        raise bad_request("Enter the SharePoint link to the report when marking it as shared.")
    prev = {"report_shared": b.report_shared, "report_type": b.report_type, "report_comments": b.report_comments,
            "report_url": b.report_url}
    if shared and not b.report_shared:
        b.report_shared_at = now_utc()
    elif not shared:
        b.report_shared_at = None
    b.report_shared, b.report_type, b.report_comments, b.report_url = shared, report_type, comments, url
    b.report_updated_by = actor.id
    db.flush()
    audit.record(db, "booking.report_updated", actor, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 previous=prev, new={"report_shared": shared, "report_type": report_type, "report_comments": comments, "report_url": url,
                          "poc_notified": bool(shared and notify_poc)})
    if shared and notify_poc:
        from . import notifications

        notifications.notify_report_shared(db, b, actor.full_name)
    return b
