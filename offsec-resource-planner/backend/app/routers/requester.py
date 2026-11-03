"""Endpoints available to every authenticated user (requesters and admins).

Everything returned here is anonymous: resources appear only as "Resource NN",
and booking details are returned only for the caller's OWN bookings.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import bad_request, not_found
from ..models import (
    ActivityType,
    Booking,
    BookingChangeRequest,
    BookingResourceLock,
    BookingStatus,
    BookingStatusHistory,
    Holiday,
    SecurityResource,
    User,
)
from ..schemas import (
    ActivityOut,
    AvailabilityQuery,
    BookingCreate,
    CancelIn,
    ChangeRequestIn,
    HolidayOut,
    ResourcePublic,
    booking_requester_out,
)
from ..services import availability, booking_service, settings_service
from ..services.calendar_engine import SchedulingError
from .common import commit, parse_range

router = APIRouter(prefix="/api", tags=["requester"])


def _own_booking(db: Session, user: User, booking_id: uuid.UUID) -> Booking:
    b = db.get(Booking, booking_id)
    # 404 (not 403) so the existence of other requesters' bookings is not disclosed (IDOR protection)
    if b is None or b.requester_id != user.id:
        raise not_found("Booking")
    return b


def _pending_cr(db: Session, booking_id: uuid.UUID) -> dict | None:
    cr = db.scalars(select(BookingChangeRequest).where(BookingChangeRequest.booking_id == booking_id,
                                                       BookingChangeRequest.status == "pending")).first()
    if not cr:
        return None
    return {"id": str(cr.id), "request_type": cr.request_type, "reason": cr.reason,
            "proposed_start_date": cr.proposed_start_date.isoformat() if cr.proposed_start_date else None,
            "created_at": cr.created_at.isoformat()}


@router.get("/resources", response_model=list[ResourcePublic])
def list_resources(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(SecurityResource).order_by(SecurityResource.sequence_no)).all()


@router.get("/activity-types", response_model=list[ActivityOut])
def list_activity_types(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(ActivityType).where(ActivityType.is_active.is_(True))
                      .order_by(ActivityType.sort_order, ActivityType.name)).all()


@router.get("/holidays", response_model=list[HolidayOut])
def list_holidays(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    start, end = parse_range(start, end, 366)
    return db.scalars(select(Holiday).where(Holiday.holiday_date.between(start, end)).order_by(Holiday.holiday_date)).all()


@router.get("/settings/public")
def public_settings(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return {
        "timezone": settings_service.get_setting(db, "timezone"),
        "today": settings_service.org_today(db).isoformat(),
        "working_weekdays": settings_service.get_setting(db, "working_weekdays"),
        "pending_expiry_enabled": settings_service.get_setting(db, "pending_expiry_enabled"),
        "pending_expiry_hours": settings_service.get_setting(db, "pending_expiry_hours"),
        "requester_direct_cancel_pending": settings_service.get_setting(db, "requester_direct_cancel_pending"),
    }


@router.get("/calendar")
def calendar(start: date, end: date, activity_type_id: uuid.UUID | None = None, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Anonymous, colour-coded availability grid (same view for every role)."""
    duration = None
    if activity_type_id:
        a = db.get(ActivityType, activity_type_id)
        if a is None:
            raise bad_request("Unknown activity type.")
        duration = a.base_duration_days
    try:
        return availability.calendar_grid(db, start, end, viewer_id=user.id, admin=False, activity_duration=duration)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)


@router.post("/availability/check")
def check_availability(body: AvailabilityQuery, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return booking_service.preview(db, user, body.resource_id, body.activity_type_id, body.start_date,
                                       body.additional_days)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)


@router.post("/bookings", status_code=201)
def submit_booking(body: BookingCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    b = booking_service.submit_booking(db, user, booking_service.BookingInput(**body.model_dump()))
    commit(db)
    return booking_requester_out(b)


@router.get("/bookings/mine")
def my_bookings(status: str | None = None, q: str | None = Query(default=None, max_length=100),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Booking).where(Booking.requester_id == user.id)
    if status:
        if status not in BookingStatus.ALL:
            raise bad_request("Invalid status filter.")
        stmt = stmt.where(Booking.status == status)
    if q:
        stmt = stmt.where(Booking.application_name.ilike(f"%{q}%"))
    rows = db.scalars(stmt.order_by(Booking.submitted_at.desc()).limit(500)).unique().all()
    return [booking_requester_out(b, _pending_cr(db, b.id)) for b in rows]


@router.get("/bookings/{booking_id}")
def get_my_booking(booking_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    b = _own_booking(db, user, booking_id)
    return booking_requester_out(b, _pending_cr(db, b.id))


@router.get("/bookings/{booking_id}/history")
def my_booking_history(booking_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Filtered history for the requester: status transitions and change requests, without admin identities/internal notes."""
    b = _own_booking(db, user, booking_id)
    hist = db.scalars(select(BookingStatusHistory).where(BookingStatusHistory.booking_id == b.id)
                      .order_by(BookingStatusHistory.changed_at)).all()
    public_reason_states = {BookingStatus.REJECTED, BookingStatus.CANCELLED, BookingStatus.EXPIRED}
    events = [{"at": h.changed_at.isoformat(), "type": "status",
               "from_status": h.from_status, "to_status": h.to_status,
               "label": BookingStatus.LABELS.get(h.to_status, h.to_status),
               "note": h.reason if h.to_status in public_reason_states else None} for h in hist]
    for cr in db.scalars(select(BookingChangeRequest).where(BookingChangeRequest.booking_id == b.id)).all():
        events.append({"at": cr.created_at.isoformat(), "type": "change_request", "request_type": cr.request_type,
                       "status": cr.status, "proposed_start_date": cr.proposed_start_date.isoformat() if cr.proposed_start_date else None,
                       "note": cr.reason})
        if cr.decided_at:
            events.append({"at": cr.decided_at.isoformat(), "type": "change_request_decision",
                           "request_type": cr.request_type, "status": cr.status, "note": cr.decision_note})
    events.sort(key=lambda e: e["at"])
    return {"booking_id": str(b.id), "events": events}


@router.post("/bookings/{booking_id}/cancel")
def cancel_my_booking(booking_id: uuid.UUID, body: CancelIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    _own_booking(db, user, booking_id)
    b = booking_service.cancel(db, user, booking_id, body.reason)
    commit(db)
    return booking_requester_out(b)


@router.post("/bookings/{booking_id}/change-requests", status_code=201)
def request_change(booking_id: uuid.UUID, body: ChangeRequestIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _own_booking(db, user, booking_id)
    result = booking_service.request_change(db, user, booking_id, body.request_type, body.reason,
                                            body.proposed_start_date, body.proposed_resource_id)
    commit(db)
    return result


@router.get("/me/dashboard")
def my_dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    today = settings_service.org_today(db)
    counts = dict(db.execute(select(Booking.status, func.count()).where(Booking.requester_id == user.id)
                             .group_by(Booking.status)).all())
    upcoming = db.scalars(select(Booking).where(Booking.requester_id == user.id, Booking.status == BookingStatus.APPROVED,
                                                Booking.end_date >= today).order_by(Booking.start_date).limit(10)).unique().all()
    active_ids = [r for r in db.scalars(select(SecurityResource.id).where(SecurityResource.is_active.is_(True)))]
    busy_today = set(db.scalars(select(BookingResourceLock.resource_id).where(
        BookingResourceLock.work_date == today, availability.active_lock_clause(db))))
    available_today = 0
    if active_ids:
        leaves = availability.load_leave_dates(db, active_ids, today, today)
        hol = availability.load_holidays(db, today, today)
        wk = availability.working_weekdays(db)
        for rid in active_ids:
            if today.weekday() in wk and today not in hol and today not in leaves[rid] and rid not in busy_today:
                available_today += 1
    window_end = today + timedelta(days=30)
    return {
        "today": today.isoformat(),
        "counts": {s: counts.get(s, 0) for s in BookingStatus.ALL},
        "available_resources_today": available_today,
        "active_resources": len(active_ids),
        "upcoming": [booking_requester_out(b) for b in upcoming],
        "upcoming_holidays": [{"date": h.holiday_date.isoformat(), "name": h.name} for h in db.scalars(
            select(Holiday).where(Holiday.holiday_date.between(today, window_end)).order_by(Holiday.holiday_date))],
    }

