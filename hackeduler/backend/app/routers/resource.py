"""Endpoints for the 'resource' role (a security engineer).

A resource user sees ONLY bookings that use their own linked resource, can record report sharing on them
(nothing else), and manages leave for their own resource. Every route requires the resource role; the
resource id always comes from the signed-in user, never from the request.
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_resource
from ..errors import bad_request, not_found
from ..models import Booking, BookingStatus, ResourceLeave, User
from ..schemas import ReportIn, Strict, booking_requester_out
from ..services import audit, conflicts, reports
from ..services.availability import now_utc
from ..services.calendar_engine import expand_ranges
from .common import commit

router = APIRouter(prefix="/api/resource", tags=["resource"], dependencies=[Depends(require_resource)])

VISIBLE = (BookingStatus.APPROVED, BookingStatus.COMPLETED)


def _mine(user: User):
    return Booking.uses_resource(user.resource_id), Booking.status.in_(VISIBLE)


def _out(b: Booking) -> dict:
    d = booking_requester_out(b).model_dump(mode="json")
    d["requester_email"] = b.requester.email if b.requester else None
    d["extra_resources"] = [r.display_name for r in b.extra_resources]
    return d


def _get_mine(db: Session, user: User, booking_id: uuid.UUID) -> Booking:
    b = db.scalars(select(Booking).where(Booking.id == booking_id, *_mine(user))).unique().first()
    if b is None:
        raise not_found("Booking")  # same answer whether it does not exist or belongs to someone else
    return b


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_resource)):
    today = date.today()
    base = select(Booking).where(*_mine(user))
    rows = db.scalars(base).unique().all()
    upcoming = sorted([b for b in rows if b.status == BookingStatus.APPROVED and b.start_date and b.start_date > today],
                      key=lambda b: b.start_date)
    in_progress = [b for b in rows if b.status == BookingStatus.APPROVED and b.start_date and b.start_date <= today
                   and (b.end_date is None or b.end_date >= today)]
    # report still to be shared: work finished (completed, or its end date has been reached)
    awaiting = [b for b in rows if not b.report_shared
                and (b.status == BookingStatus.COMPLETED or (b.end_date is not None and b.end_date <= today))]
    leaves = db.scalars(select(ResourceLeave).where(ResourceLeave.resource_id == user.resource_id,
                                                    ResourceLeave.status == "active",
                                                    ResourceLeave.end_date >= today)
                        .order_by(ResourceLeave.start_date)).unique().all()
    return {
        "resource": {"id": str(user.resource_id), "display_name": user.resource.display_name if user.resource else None},
        "counts": {
            "assigned": len(rows), "upcoming": len(upcoming), "in_progress": len(in_progress),
            "completed": sum(1 for b in rows if b.status == BookingStatus.COMPLETED),
            "reports_shared": sum(1 for b in rows if b.report_shared),
            "reports_v1": sum(1 for b in rows if b.report_shared and b.report_type == "V1"),
            "reports_met": sum(1 for b in rows if b.report_shared and b.report_type == "Met"),
            "reports_pending": len(awaiting), "upcoming_leaves": len(leaves),
        },
        "in_progress": [_out(b) for b in in_progress][:20],
        "upcoming": [_out(b) for b in upcoming][:10],
        "reports_pending": [_out(b) for b in sorted(awaiting, key=lambda b: b.end_date or today)][:10],
        "leaves": [_leave_out(lv) for lv in leaves][:10],
    }


@router.get("/bookings")
def list_bookings(status: str | None = None, report: str | None = Query(None, pattern="^(shared|pending)$"),
                  q: str | None = Query(None, max_length=100), limit: int = Query(200, le=500), offset: int = 0,
                  db: Session = Depends(get_db), user: User = Depends(require_resource)):
    stmt = select(Booking).where(*_mine(user))
    if status:
        if status not in VISIBLE:
            raise bad_request("Invalid status filter.")
        stmt = stmt.where(Booking.status == status)
    if report == "shared":
        stmt = stmt.where(Booking.report_shared.is_(True))
    elif report == "pending":
        stmt = stmt.where(Booking.report_shared.is_(False))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Booking.application_name.ilike(like), Booking.application_version.ilike(like),
                              Booking.poc_name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Booking.start_date.desc()).limit(limit).offset(offset)).unique().all()
    return {"total": total, "items": [_out(b) for b in rows]}


@router.get("/bookings/{booking_id}")
def booking_detail(booking_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_resource)):
    return _out(_get_mine(db, user, booking_id))


@router.put("/bookings/{booking_id}/report")
def set_report(booking_id: uuid.UUID, body: ReportIn, db: Session = Depends(get_db),
               user: User = Depends(require_resource)):
    b = _get_mine(db, user, booking_id)
    reports.set_report(db, b, user, shared=body.report_shared, report_type=body.report_type,
                       comments=body.report_comments)
    commit(db)
    db.refresh(b)
    return _out(b)


# ------------------------------------------------------------------ leave (own resource only)
def _leave_out(lv: ResourceLeave) -> dict:
    return {"id": str(lv.id), "start_date": lv.start_date.isoformat(), "end_date": lv.end_date.isoformat(),
            "leave_type": lv.leave_type, "reason": lv.reason, "status": lv.status}


class MyLeaveIn(Strict):
    start_date: date
    end_date: date
    leave_type: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=2000)


@router.get("/leaves")
def list_leaves(include_past: bool = False, db: Session = Depends(get_db), user: User = Depends(require_resource)):
    q = select(ResourceLeave).where(ResourceLeave.resource_id == user.resource_id, ResourceLeave.status == "active")
    if not include_past:
        q = q.where(ResourceLeave.end_date >= date.today())
    return [_leave_out(lv) for lv in db.scalars(q.order_by(ResourceLeave.start_date)).unique().all()]


@router.post("/leaves", status_code=201)
def add_leave(body: MyLeaveIn, db: Session = Depends(get_db), user: User = Depends(require_resource)):
    if body.end_date < body.start_date:
        raise bad_request("Leave end date must be on or after the start date.")
    if body.start_date < date.today():
        raise bad_request("You can only add upcoming leave.")
    if (body.end_date - body.start_date).days > 366:
        raise bad_request("Leave period cannot exceed one year.")
    r = user.resource
    lv = ResourceLeave(id=uuid.uuid4(), resource_id=user.resource_id, created_by=user.id, **body.model_dump())
    db.add(lv)
    db.flush()
    flagged = conflicts.flag_new_non_working(db, set(expand_ranges([(lv.start_date, lv.end_date)])), "leave",
                                             f"Leave for {r.display_name} ({r.engineer_name})",
                                             f"leave:{lv.id}:{lv.start_date}:{lv.end_date}", user, resource_id=r.id)
    audit.record(db, "leave.created", user, entity_type="leave", entity_id=lv.id,
                 new={"resource_id": lv.resource_id, "start_date": lv.start_date, "end_date": lv.end_date,
                      "leave_type": lv.leave_type, "reason": lv.reason, "flagged_bookings": flagged,
                      "by_resource_user": True})
    commit(db)
    db.refresh(lv)
    return {"leave": _leave_out(lv), "flagged_bookings": len(flagged)}


@router.delete("/leaves/{leave_id}")
def cancel_leave(leave_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_resource)):
    lv = db.get(ResourceLeave, leave_id)
    if lv is None or lv.status != "active" or lv.resource_id != user.resource_id:
        raise not_found("Leave")
    lv.status = "cancelled"
    db.flush()
    flagged = conflicts.flag_removed_non_working(
        db, set(expand_ranges([(lv.start_date, lv.end_date)])), "leave",
        f"Leave for {lv.resource.display_name} ({lv.resource.engineer_name})", f"leave-removed:{lv.id}", user,
        resource_id=lv.resource_id)
    audit.record(db, "leave.cancelled", user, entity_type="leave", entity_id=lv.id,
                 previous={"status": "active"}, new={"status": "cancelled", "flagged_bookings": flagged,
                                                     "by_resource_user": True})
    commit(db)
    return {"ok": True}
