"""Endpoints for the 'resource' role (a security engineer).

A resource user sees ONLY bookings that use their own linked resource, can record report sharing on them
(nothing else), and manages leave for their own resource. Every route requires the resource role; the
resource id always comes from the signed-in user, never from the request.
"""
from __future__ import annotations

import uuid
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_lead, require_resource
from ..errors import bad_request, not_found
from ..models import Booking, BookingResourceLock, BookingStatus, LockStatus, ResourceLeave, ResourceNote, User
from ..schemas import ReportIn, ResourceBookingEdit, Strict, booking_requester_out
from ..services import audit, booking_service, conflicts, reports
from ..services import availability
from ..services.availability import now_utc
from ..services.calendar_engine import expand_ranges
from .common import commit

# Leave types a resource can choose (admins' list matches). Personal leave is capped per calendar year.
LEAVE_TYPES = ["Annual leave", "Casual leave", "Personal leave", "Sick leave", "Training", "Public duty", "Other"]
PERSONAL_LEAVE = "Personal leave"
PERSONAL_LEAVE_LIMIT_DAYS = 2

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


@router.patch("/bookings/{booking_id}")
def edit_details(booking_id: uuid.UUID, body: ResourceBookingEdit, db: Session = Depends(get_db),
                 user: User = Depends(require_resource)):
    """The assigned engineer edits the details of their own approved booking (not dates, activity, resource or product).
    Audited under their name; the POC, the engineers and the requester get the 'Booking Updated' email naming them."""
    changes = body.model_dump(exclude_unset=True, exclude={"reason"})
    changes = {k: v for k, v in changes.items() if v is not None or k == "additional_comments"}
    _get_mine(db, user, booking_id)          # same 404 as everywhere else for a booking that is not theirs
    b = booking_service.modify(db, user, booking_id, changes, body.reason, as_resource=True)
    commit(db)
    db.refresh(b)
    return _out(b)


@router.put("/bookings/{booking_id}/report")
def set_report(booking_id: uuid.UUID, body: ReportIn, db: Session = Depends(get_db),
               user: User = Depends(require_resource)):
    b = _get_mine(db, user, booking_id)
    reports.set_report(db, b, user, shared=body.report_shared, report_type=body.report_type,
                       comments=body.report_comments, url=body.report_url)
    commit(db)
    db.refresh(b)
    return _out(b)


# ------------------------------------------------------------------ month calendar
@router.get("/team-calendar")
def lead_team_calendar(month: str | None = Query(None, description="YYYY-MM; default: the current month"),
                       resource_id: uuid.UUID | None = Query(None, description="Show one resource only"),
                       week: date | None = Query(None, description="Any date: just the Monday-first week containing it"),
                       db: Session = Depends(get_db), _: User = Depends(require_lead)):
    """The admin Team Calendar (every resource, read-only) for resource users who are team leads."""
    from .admin_team_calendar import build_team_calendar

    return build_team_calendar(db, month, resource_id, week)


@router.get("/calendar")
def calendar(month: str | None = Query(None, description="YYYY-MM; default: the current month"),
             week: date | None = Query(None, description="Any date: just the Monday-first week containing it (instead of a month)"),
             db: Session = Depends(get_db), user: User = Depends(require_resource)):
    """One month, as whole weeks (Monday first), for the signed-in engineer's own resource: which days are
    booked, on leave, holidays, weekends, tentatively held, or free - with the bookings behind the booked days."""
    today = date.today()
    if week is not None:                       # just one Monday-first week
        if not (today.year - 5 <= week.year <= today.year + 5):
            raise bad_request("week must be within five years of today.")
        first = grid_start = week - timedelta(days=week.weekday())
        last = grid_end = grid_start + timedelta(days=6)
    else:
        if month is None:
            first = today.replace(day=1)
        else:
            m = re.fullmatch(r"(\d{4})-(\d{2})", month)
            if not m or not (1 <= int(m.group(2)) <= 12) or not (today.year - 5 <= int(m.group(1)) <= today.year + 5):
                raise bad_request("month must look like 2026-11 (within five years of today).")
            first = date(int(m.group(1)), int(m.group(2)), 1)
        next_first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = next_first - timedelta(days=1)
        grid_start = first - timedelta(days=first.weekday())
        grid_end = last + timedelta(days=6 - last.weekday())

    rid = user.resource_id
    weekdays = availability.working_weekdays(db)
    holidays = availability.load_holidays(db, grid_start, grid_end)
    leaves = db.scalars(select(ResourceLeave).where(
        ResourceLeave.resource_id == rid, ResourceLeave.status == "active",
        ResourceLeave.start_date <= grid_end, ResourceLeave.end_date >= grid_start)).all()
    leave_by_day: dict[date, ResourceLeave] = {}
    for lv in leaves:
        for d in expand_ranges([(max(lv.start_date, grid_start), min(lv.end_date, grid_end))]):
            leave_by_day.setdefault(d, lv)
    notes_by_day: dict[date, list] = {}
    for n in db.scalars(select(ResourceNote).where(ResourceNote.resource_id == rid,
                                                   ResourceNote.note_date.between(grid_start, grid_end))
                        .order_by(ResourceNote.created_at)).all():
        notes_by_day.setdefault(n.note_date, []).append({"id": str(n.id), "note": n.note})
    # days actually reserved for this resource (per-resource slices of multi-resource bookings included)
    locks = db.execute(select(BookingResourceLock.work_date, BookingResourceLock.booking_id, BookingResourceLock.lock_status,
                              Booking.status).join(Booking, Booking.id == BookingResourceLock.booking_id)
                       .where(BookingResourceLock.resource_id == rid, availability.active_lock_clause(db),
                              BookingResourceLock.work_date.between(grid_start, grid_end))).all()
    booked: dict[date, list[uuid.UUID]] = {}
    tentative: set[date] = set()
    for d, bid, lock_status, b_status in locks:
        if lock_status == LockStatus.CONFIRMED and b_status in VISIBLE:
            booked.setdefault(d, []).append(bid)
        else:
            tentative.add(d)      # held by a request that is not approved yet: no details are shown
    bookings = {}
    if booked:
        ids = {b for v in booked.values() for b in v}
        for b in db.scalars(select(Booking).where(Booking.id.in_(ids))).unique().all():
            bookings[str(b.id)] = _out(b)

    days, counts = [], {"working_days": 0, "booked": 0, "leave": 0, "free": 0, "tentative": 0, "holidays": 0, "conflicts": 0}
    d = grid_start
    while d <= grid_end:
        lv, hol = leave_by_day.get(d), holidays.get(d)
        if d in booked and lv:
            state = "conflict"
        elif d in booked:
            state = "booked"
        elif hol:
            state = "holiday"
        elif d.weekday() not in weekdays:
            state = "weekend"
        elif lv:
            state = "leave"
        elif d in tentative:
            state = "tentative"
        else:
            state = "free"
        in_month = first <= d <= last
        if in_month:
            if d.weekday() in weekdays and not hol:
                counts["working_days"] += 1
            if hol:
                counts["holidays"] += 1
            key = {"booked": "booked", "conflict": "conflicts", "leave": "leave", "tentative": "tentative", "free": "free"}.get(state)
            if key:
                counts[key] += 1
        days.append({"date": d.isoformat(), "in_month": in_month, "state": state,
                     "booking_ids": [str(b) for b in booked.get(d, [])],
                     "holiday": hol, "notes": notes_by_day.get(d, []),
                     "leave": ({"id": str(lv.id), "leave_type": lv.leave_type, "reason": lv.reason,
                                "start_date": lv.start_date.isoformat(), "end_date": lv.end_date.isoformat()} if lv else None)})
        d += timedelta(days=1)
    return {"month": first.strftime("%Y-%m"), "week": first.isoformat() if week is not None else None, "today": today.isoformat(), "first_day": first.isoformat(), "last_day": last.isoformat(),
            "days": days, "bookings": bookings, "summary": counts,
            "leave_types": LEAVE_TYPES,
            "personal_leave": {"year": first.year, "limit": PERSONAL_LEAVE_LIMIT_DAYS,
                               "used": _personal_days_used(db, user, first.year)}}


# ------------------------------------------------------------------ leave (own resource only)
def _leave_out(lv: ResourceLeave) -> dict:
    return {"id": str(lv.id), "start_date": lv.start_date.isoformat(), "end_date": lv.end_date.isoformat(),
            "leave_type": lv.leave_type, "reason": lv.reason, "status": lv.status}


class MyLeaveIn(Strict):
    start_date: date
    end_date: date
    leave_type: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=2000)


def _personal_days_used(db: Session, user: User, year: int, exclude: uuid.UUID | None = None,
                        extra: tuple[date, date] | None = None) -> int:
    """Working days of personal leave in a calendar year (active leave of this resource, plus an optional new range)."""
    y0, y1 = date(year, 1, 1), date(year, 12, 31)
    q = select(ResourceLeave).where(ResourceLeave.resource_id == user.resource_id, ResourceLeave.status == "active",
                                    ResourceLeave.leave_type == PERSONAL_LEAVE,
                                    ResourceLeave.start_date <= y1, ResourceLeave.end_date >= y0)
    ranges = [(lv.start_date, lv.end_date) for lv in db.scalars(q).all() if lv.id != exclude]
    if extra:
        ranges.append(extra)
    weekdays = availability.working_weekdays(db)
    days: set[date] = set()
    for s, e in ranges:
        days.update(d for d in expand_ranges([(max(s, y0), min(e, y1))]) if d.weekday() in weekdays)
    holidays = availability.load_holidays(db, y0, y1)
    return len([d for d in days if d not in holidays])


class NoteIn(Strict):
    note_date: date
    note: str = Field(min_length=1, max_length=2000)


class NoteEdit(Strict):
    note: str = Field(min_length=1, max_length=2000)


def _own_note(db: Session, user: User, note_id: uuid.UUID) -> ResourceNote:
    n = db.get(ResourceNote, note_id)
    if n is None or n.resource_id != user.resource_id:
        raise not_found("Note")
    return n


@router.post("/notes", status_code=201)
def add_note(body: NoteIn, db: Session = Depends(get_db), user: User = Depends(require_resource)):
    text = body.note.strip()
    if not text:
        raise bad_request("Write something in the note first.")
    n = ResourceNote(id=uuid.uuid4(), resource_id=user.resource_id, note_date=body.note_date, note=text, created_by=user.id)
    db.add(n)
    commit(db)
    return {"id": str(n.id), "note_date": n.note_date.isoformat(), "note": n.note}


@router.put("/notes/{note_id}")
def edit_note(note_id: uuid.UUID, body: NoteEdit, db: Session = Depends(get_db), user: User = Depends(require_resource)):
    n = _own_note(db, user, note_id)
    text = body.note.strip()
    if not text:
        raise bad_request("Write something in the note first.")
    n.note = text
    commit(db)
    return {"id": str(n.id), "note_date": n.note_date.isoformat(), "note": n.note}


@router.delete("/notes/{note_id}")
def delete_note(note_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_resource)):
    db.delete(_own_note(db, user, note_id))
    commit(db)
    return {"ok": True}


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
    if body.leave_type == PERSONAL_LEAVE:
        for year in sorted({body.start_date.year, body.end_date.year}):
            used = _personal_days_used(db, user, year)
            total = _personal_days_used(db, user, year, extra=(body.start_date, body.end_date))
            if total > PERSONAL_LEAVE_LIMIT_DAYS:
                raise bad_request(f"Personal leave is limited to {PERSONAL_LEAVE_LIMIT_DAYS} days per calendar year; "
                                  f"you have used {used} in {year} and this request would make it {total}.")
    r = user.resource
    lv = ResourceLeave(id=uuid.uuid4(), resource_id=user.resource_id, created_by=user.id, **body.model_dump())
    db.add(lv)
    db.flush()
    # Leave the resource marks themselves is just recorded. Existing bookings are NOT touched: their dates, status
    # and review flag stay as they are, and no conflict is opened or POC emailed. The overlap is only reported back
    # (and kept in the audit trail); the days show as leave + booked on the calendars.
    overlapping = conflicts.bookings_locking_dates(db, set(expand_ranges([(lv.start_date, lv.end_date)])), r.id)
    audit.record(db, "leave.created", user, entity_type="leave", entity_id=lv.id,
                 new={"resource_id": lv.resource_id, "start_date": lv.start_date, "end_date": lv.end_date,
                      "leave_type": lv.leave_type, "reason": lv.reason, "overlapping_bookings": list(overlapping),
                      "by_resource_user": True})
    commit(db)
    db.refresh(lv)
    return {"leave": _leave_out(lv), "overlapping_bookings": len(overlapping)}


@router.delete("/leaves/{leave_id}")
def cancel_leave(leave_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_resource)):
    lv = db.get(ResourceLeave, leave_id)
    if lv is None or lv.status != "active" or lv.resource_id != user.resource_id:
        raise not_found("Leave")
    lv.status = "cancelled"
    db.flush()
    audit.record(db, "leave.cancelled", user, entity_type="leave", entity_id=lv.id,
                 previous={"status": "active"}, new={"status": "cancelled", "by_resource_user": True})
    commit(db)
    return {"ok": True}
