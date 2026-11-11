"""Report-sharing on a booking: shared yes/no, which report (V1 or Met) and free-text comments.

Used by the assigned engineer (resource role) and by admins. Nothing else on the booking changes.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..errors import bad_request
from ..models import Booking, BookingStatus, User
from . import audit
from .availability import now_utc

REPORT_TYPES = ("V1", "Met")
REPORTABLE = (BookingStatus.APPROVED, BookingStatus.COMPLETED)


def set_report(db: Session, b: Booking, actor: User, *, shared: bool, report_type: str | None,
               comments: str | None) -> Booking:
    if b.status not in REPORTABLE:
        raise bad_request("Report details can only be recorded on approved or completed bookings.")
    if report_type is not None and report_type not in REPORT_TYPES:
        raise bad_request("Report type must be V1 or Met.")
    if shared and not report_type:
        raise bad_request("Choose the report type (V1 or Met) when marking the report as shared.")
    comments = (comments or "").strip() or None
    prev = {"report_shared": b.report_shared, "report_type": b.report_type, "report_comments": b.report_comments}
    if shared and not b.report_shared:
        b.report_shared_at = now_utc()
    elif not shared:
        b.report_shared_at = None
    b.report_shared, b.report_type, b.report_comments = shared, report_type, comments
    b.report_updated_by = actor.id
    db.flush()
    audit.record(db, "booking.report_updated", actor, entity_type="booking", entity_id=b.id, booking_id=b.id,
                 previous=prev, new={"report_shared": shared, "report_type": report_type, "report_comments": comments})
    return b
