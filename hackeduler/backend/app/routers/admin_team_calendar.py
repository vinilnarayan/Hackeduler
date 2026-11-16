"""Team Calendar (admin): one month, every security resource's bookings, leave and the holidays, day by day."""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..errors import bad_request, not_found
from ..models import Booking, BookingResourceLock, LockStatus, ResourceLeave, SecurityResource
from ..services import availability
from ..services.calendar_engine import expand_ranges

router = APIRouter(prefix="/api/admin", tags=["admin-team-calendar"], dependencies=[Depends(require_admin)])


def month_bounds(month: str | None) -> tuple[date, date, date, date]:
    """(first, last, grid_start, grid_end) of a month, as whole Monday-first weeks."""
    today = date.today()
    if month is None:
        first = today.replace(day=1)
    else:
        m = re.fullmatch(r"(\d{4})-(\d{2})", month)
        if not m or not (1 <= int(m.group(2)) <= 12) or not (today.year - 5 <= int(m.group(1)) <= today.year + 5):
            raise bad_request("month must look like 2026-11 (within five years of today).")
        first = date(int(m.group(1)), int(m.group(2)), 1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first, last, first - timedelta(days=first.weekday()), last + timedelta(days=6 - last.weekday())


@router.get("/team-calendar")
def team_calendar(month: str | None = Query(None, description="YYYY-MM; default: the current month"),
                  resource_id: uuid.UUID | None = Query(None, description="Show one resource only"),
                  db: Session = Depends(get_db)):
    first, last, grid_start, grid_end = month_bounds(month)
    resources = db.scalars(select(SecurityResource).where(SecurityResource.deleted_at.is_(None))
                           .order_by(SecurityResource.sequence_no)).all()
    if resource_id is not None and resource_id not in {r.id for r in resources}:
        raise not_found("Resource")
    names = {r.id: r for r in resources}
    weekdays = availability.working_weekdays(db)
    holidays = availability.load_holidays(db, grid_start, grid_end)

    lock_q = (select(BookingResourceLock.work_date, BookingResourceLock.resource_id, BookingResourceLock.lock_status, Booking)
              .join(Booking, Booking.id == BookingResourceLock.booking_id)
              .where(availability.active_lock_clause(db), BookingResourceLock.work_date.between(grid_start, grid_end)))
    leave_q = select(ResourceLeave).where(ResourceLeave.status == "active", ResourceLeave.start_date <= grid_end,
                                          ResourceLeave.end_date >= grid_start)
    if resource_id is not None:
        lock_q = lock_q.where(BookingResourceLock.resource_id == resource_id)
        leave_q = leave_q.where(ResourceLeave.resource_id == resource_id)

    entries: dict[date, list[dict]] = {}
    for d, rid, lock_status, b in db.execute(lock_q.order_by(BookingResourceLock.work_date)).unique().all():
        r = names.get(rid)
        if r is None:
            continue
        entries.setdefault(d, []).append({
            "booking_id": str(b.id), "resource_id": str(rid), "resource_name": r.display_name, "engineer_name": r.engineer_name,
            "application_name": b.application_name, "application_version": b.application_version,
            "activity_name": b.activity_name_snapshot, "status": b.status, "tentative": lock_status != LockStatus.CONFIRMED,
            "start_date": b.start_date.isoformat() if b.start_date else None, "end_date": b.end_date.isoformat() if b.end_date else None,
        })
    leaves_by_day: dict[date, list[dict]] = {}
    for lv in db.scalars(leave_q).unique().all():
        r = names.get(lv.resource_id)
        if r is None:
            continue
        for d in expand_ranges([(max(lv.start_date, grid_start), min(lv.end_date, grid_end))]):
            leaves_by_day.setdefault(d, []).append({"leave_id": str(lv.id), "resource_id": str(r.id), "resource_name": r.display_name,
                                                    "engineer_name": r.engineer_name, "leave_type": lv.leave_type})

    days, counts = [], {"working_days": 0, "booked_days": 0, "leave_days": 0, "holidays": 0}
    d = grid_start
    while d <= grid_end:
        hol, working = holidays.get(d), d.weekday() in weekdays
        day_entries = sorted(entries.get(d, []), key=lambda e: (e["resource_name"], e["application_name"]))
        day_leaves = sorted(leaves_by_day.get(d, []), key=lambda e: e["resource_name"])
        if first <= d <= last:
            counts["working_days"] += 1 if working and not hol else 0
            counts["holidays"] += 1 if hol else 0
            counts["booked_days"] += len(day_entries)
            counts["leave_days"] += len(day_leaves) if working and not hol else 0
        days.append({"date": d.isoformat(), "in_month": first <= d <= last, "weekend": not working, "holiday": hol,
                     "entries": day_entries, "leaves": day_leaves})
        d += timedelta(days=1)
    return {"month": first.strftime("%Y-%m"), "today": date.today().isoformat(), "days": days, "summary": counts,
            "resources": [{"id": str(r.id), "display_name": r.display_name, "engineer_name": r.engineer_name,
                           "is_active": r.is_active} for r in resources]}
