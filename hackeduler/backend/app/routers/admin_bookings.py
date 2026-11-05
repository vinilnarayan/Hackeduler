"""Admin booking management, Force Allocate, conflicts, change requests and audit.

The router-level ``require_admin`` dependency guarantees every route here
(including all Force Allocate paths) rejects non-admins with 403. The booking
service re-checks the role as defence in depth.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..errors import bad_request, not_found
from ..models import (
    AuditLog,
    Booking,
    BookingChangeRequest,
    BookingConflict,
    BookingResourceLock,
    BookingStatus,
    BookingStatusHistory,
    EmailNotificationLog,
    ResourceLeave,
    User,
)
from ..schemas import (
    AdminAvailabilityQuery,
    AdminBookingCreate,
    ApproveIn,
    AuditOut,
    BookingModify,
    CancelIn,
    ChangeDecisionIn,
    CompleteIn,
    ConflictResolveIn,
    ForceIn,
    RejectIn,
    booking_admin_out,
)
from ..services import availability, booking_service, conflicts
from ..services.booking_service import ForceOptions
from ..services.calendar_engine import SchedulingError
from .common import commit

router = APIRouter(prefix="/api/admin", tags=["admin-bookings"], dependencies=[Depends(require_admin)])


def _force(f: ForceIn | None) -> ForceOptions | None:
    return ForceOptions(confirm=f.confirm, reason=f.reason) if f else None


def _open_conflicts(db: Session, booking_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(BookingConflict).where(
        BookingConflict.status == "open",
        or_(BookingConflict.booking_id == booking_id, BookingConflict.conflicting_booking_id == booking_id))) or 0


def _pending_cr(db: Session, booking_id: uuid.UUID) -> dict | None:
    cr = db.scalars(select(BookingChangeRequest).where(BookingChangeRequest.booking_id == booking_id,
                                                       BookingChangeRequest.status == "pending")).first()
    return _cr_out(cr) if cr else None


def _cr_out(cr: BookingChangeRequest) -> dict:
    return {"id": str(cr.id), "booking_id": str(cr.booking_id), "request_type": cr.request_type, "reason": cr.reason,
            "proposed_start_date": cr.proposed_start_date.isoformat() if cr.proposed_start_date else None,
            "proposed_resource_id": str(cr.proposed_resource_id) if cr.proposed_resource_id else None,
            "status": cr.status, "decided_by": str(cr.decided_by) if cr.decided_by else None,
            "decided_at": cr.decided_at.isoformat() if cr.decided_at else None, "decision_note": cr.decision_note,
            "created_at": cr.created_at.isoformat(),
            "booking": {"application_name": cr.booking.application_name, "status": cr.booking.status,
                        "start_date": cr.booking.start_date.isoformat() if cr.booking.start_date else None,
                        "end_date": cr.booking.end_date.isoformat() if cr.booking.end_date else None,
                        "resource_display_name": cr.booking.resource.display_name if cr.booking.resource else None,
                        "engineer_name": cr.booking.resource.engineer_name if cr.booking.resource else None,
                        "requester_name": cr.booking.requester.full_name}}


def _out(db: Session, b: Booking):
    return booking_admin_out(b, _pending_cr(db, b.id), _open_conflicts(db, b.id))


# =============================================================== calendar
@router.get("/calendar")
def admin_calendar(start: date, end: date, activity_type_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    from ..models import ActivityType

    duration = None
    if activity_type_id:
        a = db.get(ActivityType, activity_type_id)
        duration = a.base_duration_days if a else None
    try:
        grid = availability.calendar_grid(db, start, end, viewer_id=admin.id, admin=True, activity_duration=duration)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)
    leaves = db.scalars(select(ResourceLeave).where(ResourceLeave.status == "active", ResourceLeave.start_date <= end,
                                                    ResourceLeave.end_date >= start)).unique().all()
    grid["leaves"] = [{"id": str(lv.id), "resource_id": str(lv.resource_id), "start_date": lv.start_date.isoformat(),
                       "end_date": lv.end_date.isoformat(), "leave_type": lv.leave_type, "reason": lv.reason}
                      for lv in leaves]
    bookings = db.scalars(select(Booking).where(Booking.start_date <= end, Booking.end_date >= start)
                          .order_by(Booking.start_date)).unique().all()
    grid["bookings"] = [_out(db, b).model_dump(mode="json") for b in bookings]
    grid["open_conflicts"] = db.scalar(select(func.count()).select_from(BookingConflict).where(BookingConflict.status == "open"))
    return grid


# =============================================================== bookings
@router.get("/bookings")
def list_bookings(
    status: str | None = None, resource_id: uuid.UUID | None = None, activity_type_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100), start: date | None = None, end: date | None = None,
    needs_review: bool | None = None, pci: bool | None = None, limit: int = Query(200, le=1000), offset: int = 0,
    product_id: uuid.UUID | None = None, implementation_id: uuid.UUID | None = None, requires_resource: bool | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Booking)
    if product_id:
        stmt = stmt.where(Booking.product_id == product_id)
    if implementation_id:
        stmt = stmt.where(Booking.implementation_id == implementation_id)
    if requires_resource is not None:
        stmt = stmt.where(Booking.requires_resource.is_(requires_resource))
    if status:
        if status not in BookingStatus.ALL:
            raise bad_request("Invalid status filter.")
        stmt = stmt.where(Booking.status == status)
    if resource_id:
        stmt = stmt.where(Booking.resource_id == resource_id)
    if activity_type_id:
        stmt = stmt.where(Booking.activity_type_id == activity_type_id)
    if start:
        stmt = stmt.where(Booking.end_date >= start)
    if end:
        stmt = stmt.where(Booking.start_date <= end)
    if needs_review is not None:
        stmt = stmt.where(Booking.needs_review.is_(needs_review))
    if pci is not None:
        stmt = stmt.where(Booking.pci_dss_scope.is_(pci))
    if q:
        like = f"%{q}%"
        conds = [Booking.application_name.ilike(like), Booking.poc_name.ilike(like), Booking.poc_email.ilike(like)]
        try:
            conds.append(Booking.id == uuid.UUID(q))
        except ValueError:
            pass
        stmt = stmt.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Booking.submitted_at.desc()).limit(limit).offset(offset)).unique().all()
    return {"total": total, "items": [_out(db, b) for b in rows]}


@router.get("/bookings/{booking_id}")
def booking_detail(booking_id: uuid.UUID, db: Session = Depends(get_db)):
    b = db.get(Booking, booking_id)
    if b is None:
        raise not_found("Booking")
    history = db.scalars(select(BookingStatusHistory).where(BookingStatusHistory.booking_id == b.id)
                         .order_by(BookingStatusHistory.changed_at)).all()
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({h.changed_by for h in history if h.changed_by}))).unique()}
    locks = db.scalars(select(BookingResourceLock).where(BookingResourceLock.booking_id == b.id)
                       .order_by(BookingResourceLock.created_at, BookingResourceLock.work_date)).all()
    audits = db.scalars(select(AuditLog).where(AuditLog.booking_id == b.id).order_by(AuditLog.created_at)).all()
    confs = db.scalars(select(BookingConflict).where(or_(BookingConflict.booking_id == b.id,
                                                         BookingConflict.conflicting_booking_id == b.id))
                       .order_by(BookingConflict.created_at.desc())).unique().all()
    crs = db.scalars(select(BookingChangeRequest).where(BookingChangeRequest.booking_id == b.id)
                     .order_by(BookingChangeRequest.created_at.desc())).unique().all()
    emails = db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.booking_id == b.id)
                        .order_by(EmailNotificationLog.created_at.desc())).all()
    return {
        "booking": _out(db, b),
        "status_history": [{"from_status": h.from_status, "to_status": h.to_status, "reason": h.reason,
                            "changed_at": h.changed_at.isoformat(),
                            "changed_by": users[h.changed_by].email if h.changed_by in users else "system"} for h in history],
        "locks": [{"work_date": lk.work_date.isoformat(), "lock_status": lk.lock_status, "is_forced": lk.is_forced,
                   "resource_id": str(lk.resource_id), "expires_at": lk.expires_at.isoformat() if lk.expires_at else None}
                  for lk in locks],
        "audit": [AuditOut.model_validate(a) for a in audits],
        "conflicts": [_conflict_out(c) for c in confs],
        "change_requests": [_cr_out(c) for c in crs],
        "emails": [{"id": str(e.id), "template_key": e.template_key, "recipient": e.recipient, "status": e.status,
                    "attempts": e.attempts, "last_error": e.last_error, "created_at": e.created_at.isoformat()} for e in emails],
    }


@router.post("/availability/check")
def admin_check(body: AdminAvailabilityQuery, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Admin preview: like the requester check but includes conflicting booking IDs and inactive resources."""
    try:
        return booking_service.preview(db, admin, body.resource_id, body.activity_type_id, body.start_date,
                                       body.additional_days, exclude_booking_id=body.exclude_booking_id)
    except SchedulingError as e:
        raise bad_request(e.message, e.code)


@router.post("/bookings", status_code=201)
def admin_create(body: AdminBookingCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    data = body.model_dump(exclude={"initial_status", "duration_days", "end_date", "reason", "force"})
    b = booking_service.admin_create_booking(
        db, admin, booking_service.BookingInput(**data), initial_status=body.initial_status,
        duration_override=body.duration_days, end_date_override=body.end_date, force=_force(body.force), reason=body.reason)
    commit(db)
    return _out(db, b)


@router.post("/bookings/{booking_id}/approve")
def approve(booking_id: uuid.UUID, body: ApproveIn | None = None, db: Session = Depends(get_db),
            admin: User = Depends(require_admin)):
    b = booking_service.approve(db, admin, booking_id, _force(body.force if body else None))
    commit(db)
    return _out(db, b)


@router.post("/bookings/{booking_id}/reject")
def reject(booking_id: uuid.UUID, body: RejectIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    b = booking_service.reject(db, admin, booking_id, body.reason)
    commit(db)
    return _out(db, b)


@router.post("/bookings/{booking_id}/cancel")
def cancel(booking_id: uuid.UUID, body: CancelIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    b = booking_service.cancel(db, admin, booking_id, body.reason)
    commit(db)
    return _out(db, b)


@router.post("/bookings/{booking_id}/complete")
def complete(booking_id: uuid.UUID, body: CompleteIn | None = None, db: Session = Depends(get_db),
             admin: User = Depends(require_admin)):
    """Mark an approved booking that needs no security resource (e.g. a scan) as completed."""
    b = booking_service.mark_completed(db, admin, booking_id, body.note if body else None)
    commit(db)
    return _out(db, b)


@router.patch("/bookings/{booking_id}")
def modify(booking_id: uuid.UUID, body: BookingModify, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    changes = body.model_dump(exclude_unset=True, exclude={"reason", "force"})
    changes = {k: v for k, v in changes.items() if v is not None or k == "additional_comments"}
    b = booking_service.modify(db, admin, booking_id, changes, body.reason, _force(body.force))
    commit(db)
    return _out(db, b)


# =============================================================== change requests
@router.get("/change-requests")
def list_change_requests(status: str | None = "pending", db: Session = Depends(get_db)):
    q = select(BookingChangeRequest).order_by(BookingChangeRequest.created_at.desc())
    if status:
        q = q.where(BookingChangeRequest.status == status)
    return [_cr_out(c) for c in db.scalars(q.limit(500)).unique().all()]


@router.post("/change-requests/{cr_id}/decide")
def decide_change_request(cr_id: uuid.UUID, body: ChangeDecisionIn, db: Session = Depends(get_db),
                          admin: User = Depends(require_admin)):
    cr = booking_service.decide_change_request(db, admin, cr_id, body.approve, body.note, _force(body.force))
    commit(db)
    return _cr_out(cr)


# =============================================================== conflicts
def _conflict_out(c: BookingConflict) -> dict:
    return {
        "id": str(c.id), "booking_id": str(c.booking_id),
        "conflicting_booking_id": str(c.conflicting_booking_id) if c.conflicting_booking_id else None,
        "resource_id": str(c.resource_id) if c.resource_id else None,
        "resource_display_name": c.resource.display_name if c.resource else None,
        "engineer_name": c.resource.engineer_name if c.resource else None,
        "application_name": c.booking.application_name,
        "booking_status": c.booking.status,
        "booking_start_date": c.booking.start_date.isoformat(), "booking_end_date": c.booking.end_date.isoformat(),
        "conflicting_application_name": c.conflicting_booking.application_name if c.conflicting_booking else None,
        "conflicting_booking_status": c.conflicting_booking.status if c.conflicting_booking else None,
        "conflicting_start_date": c.conflicting_booking.start_date.isoformat() if c.conflicting_booking else None,
        "conflicting_end_date": c.conflicting_booking.end_date.isoformat() if c.conflicting_booking else None,
        "conflict_type": c.conflict_type, "description": c.description,
        "conflict_start_date": c.conflict_start_date.isoformat() if c.conflict_start_date else None,
        "conflict_end_date": c.conflict_end_date.isoformat() if c.conflict_end_date else None,
        "status": c.status, "resolution_note": c.resolution_note,
        "resolved_by": str(c.resolved_by) if c.resolved_by else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat(),
    }


@router.get("/conflicts")
def list_conflicts(status: str | None = "open", conflict_type: str | None = None, booking_id: uuid.UUID | None = None,
                   db: Session = Depends(get_db)):
    q = select(BookingConflict).order_by(BookingConflict.created_at.desc())
    if status:
        q = q.where(BookingConflict.status == status)
    if conflict_type:
        q = q.where(BookingConflict.conflict_type == conflict_type)
    if booking_id:
        q = q.where(or_(BookingConflict.booking_id == booking_id, BookingConflict.conflicting_booking_id == booking_id))
    rows = db.scalars(q.limit(1000)).unique().all()
    resolvers = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_({c.resolved_by for c in rows if c.resolved_by}))).unique()}
    out = []
    for c in rows:
        d = _conflict_out(c)
        d["resolved_by_email"] = resolvers.get(c.resolved_by)
        out.append(d)
    return out


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: uuid.UUID, body: ConflictResolveIn, db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    c = db.get(BookingConflict, conflict_id)
    if c is None:
        raise not_found("Conflict")
    if c.status != "open":
        raise bad_request("Conflict is already resolved.", "invalid_state")
    conflicts.resolve(db, c, admin, body.resolution_note.strip())
    commit(db)
    return _conflict_out(c)


# =============================================================== audit (read-only; no update/delete endpoints exist)
@router.get("/audit")
def audit_log(booking_id: uuid.UUID | None = None, actor: str | None = Query(None, max_length=254),
              action: str | None = Query(None, max_length=100), start: date | None = None, end: date | None = None,
              entity_type: str | None = None, limit: int = Query(200, le=1000), offset: int = 0,
              db: Session = Depends(get_db)):
    q = select(AuditLog)
    if booking_id:
        q = q.where(AuditLog.booking_id == booking_id)
    if actor:
        q = q.where(AuditLog.actor_email.ilike(f"%{actor}%"))
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if start:
        q = q.where(AuditLog.created_at >= datetime.combine(start, time.min))
    if end:
        q = q.where(AuditLog.created_at < datetime.combine(end + timedelta(days=1), time.min))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [AuditOut.model_validate(a) for a in rows]}


@router.post("/jobs/run")
def run_jobs(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Manually trigger expiry/completion sweeps (the worker also runs them periodically)."""
    expired = booking_service.expire_stale_pending(db)
    deactivated = booking_service.apply_scheduled_deactivations(db)
    completed = booking_service.complete_past_bookings(db)
    commit(db)
    return {"expired": [str(x) for x in expired], "deactivated_resources": [str(x) for x in deactivated],
            "completed": [str(x) for x in completed]}

