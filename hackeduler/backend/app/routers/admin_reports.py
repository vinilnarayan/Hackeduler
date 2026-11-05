"""Admin dashboard metrics and CSV/Excel exports."""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..errors import bad_request
from ..models import (
    Booking,
    BookingConflict,
    BookingResourceLock,
    BookingStatus,
    Holiday,
    LockStatus,
    SecurityResource,
    User,
)
from ..schemas import booking_admin_out
from ..services import audit, availability, settings_service
from ..services.calendar_engine import WorkCalendar
from .common import commit

router = APIRouter(prefix="/api/admin", tags=["admin-reports"], dependencies=[Depends(require_admin)])


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


@router.get("/dashboard")
def dashboard(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    today = settings_service.org_today(db)
    start = start or _month_start(today - timedelta(days=150))
    end = end or (_next_month(_next_month(_month_start(today))) - timedelta(days=1)) + timedelta(days=150)
    if end < start or (end - start).days > 800:
        raise bad_request("Invalid date range (max ~2 years).")

    resources = list(db.scalars(select(SecurityResource).where(SecurityResource.deleted_at.is_(None)).order_by(SecurityResource.sequence_no)))
    active = [r for r in resources if r.is_active]
    rids = [r.id for r in resources]
    holidays = availability.load_holidays(db, min(start, today), max(end, today))
    leaves = availability.load_leave_dates(db, rids, min(start, today), max(end, today)) if rids else {}
    wk = availability.working_weekdays(db)

    # ---- today KPIs
    today_locks = db.execute(select(BookingResourceLock.resource_id, BookingResourceLock.lock_status)
                             .where(BookingResourceLock.work_date == today, availability.active_lock_clause(db))).all()
    occupied = {rid for rid, st in today_locks if st == LockStatus.CONFIRMED}
    reserved = {rid for rid, st in today_locks if st == LockStatus.PENDING} - occupied
    on_leave = [r for r in active if today in leaves.get(r.id, frozenset())]
    working_today = today.weekday() in wk and today not in holidays
    available_today = [r for r in active if working_today and r.id not in occupied and r.id not in reserved
                       and today not in leaves.get(r.id, frozenset())]

    # ---- utilisation (approved/completed confirmed locks vs capacity)
    used_rows = db.execute(
        select(BookingResourceLock.resource_id, BookingResourceLock.work_date)
        .join(Booking, Booking.id == BookingResourceLock.booking_id)
        .where(BookingResourceLock.work_date.between(start, end), BookingResourceLock.lock_status == LockStatus.CONFIRMED,
               Booking.status.in_([BookingStatus.APPROVED, BookingStatus.COMPLETED]))
    ).all()
    used_by_month: Counter = Counter()
    used_by_resource: Counter = Counter()
    used_pairs = set()
    for rid, d in used_rows:
        if (rid, d) in used_pairs:
            continue  # forced overlaps count once
        used_pairs.add((rid, d))
        used_by_month[_month_start(d)] += 1
        used_by_resource[rid] += 1
    cap_by_month: Counter = Counter()
    cap_by_resource: Counter = Counter()
    for r in active:
        cal = WorkCalendar(holidays=holidays, leave_dates=leaves.get(r.id, frozenset()), working_weekdays=wk)
        d = start
        while d <= end:
            if cal.is_eligible(d) and not r.inactive_on(d):
                cap_by_month[_month_start(d)] += 1
                cap_by_resource[r.id] += 1
            d += timedelta(days=1)
    months = []
    m = _month_start(start)
    while m <= end:
        months.append(m)
        m = _next_month(m)
    total_cap = sum(cap_by_month.values())
    total_used = sum(v for k, v in used_by_resource.items() if k in {r.id for r in active})

    # ---- booking stats
    in_range = db.scalars(select(Booking).where(Booking.start_date <= end, Booking.end_date >= start)).unique().all()
    status_counts = Counter(b.status for b in in_range)
    all_status = dict(db.execute(select(Booking.status, func.count()).group_by(Booking.status)).all())
    activity_counts = Counter(b.activity_name_snapshot for b in in_range
                              if b.status in (BookingStatus.APPROVED, BookingStatus.PENDING, BookingStatus.COMPLETED))
    volume = dict(db.execute(
        select(func.date_trunc("month", Booking.submitted_at).label("m"), func.count())
        .where(func.date(Booking.submitted_at).between(start, end)).group_by("m")).all())
    volume_by_month = defaultdict(int, {k.date().replace(day=1): v for k, v in volume.items()})

    upcoming = db.scalars(select(Booking).where(Booking.status == BookingStatus.APPROVED, Booking.end_date >= today)
                          .order_by(Booking.start_date).limit(10)).unique().all()
    pending = db.scalars(select(Booking).where(Booking.status == BookingStatus.PENDING)
                         .order_by(Booking.submitted_at).limit(10)).unique().all()
    upcoming_holidays = db.scalars(select(Holiday).where(Holiday.holiday_date.between(today, today + timedelta(days=90)))
                                   .order_by(Holiday.holiday_date)).all()
    open_conflicts = db.scalar(select(func.count()).select_from(BookingConflict).where(BookingConflict.status == "open"))

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "today": today.isoformat(),
        "kpis": {
            "total_resources": len(resources),
            "active_resources": len(active),
            "available_today": len(available_today),
            "occupied_today": len(occupied),
            "reserved_today": len(reserved),
            "on_leave_today": len(on_leave),
            "pending_requests": all_status.get(BookingStatus.PENDING, 0),
            "approved": all_status.get(BookingStatus.APPROVED, 0),
            "rejected": all_status.get(BookingStatus.REJECTED, 0),
            "cancelled": all_status.get(BookingStatus.CANCELLED, 0),
            "completed": all_status.get(BookingStatus.COMPLETED, 0),
            "expired": all_status.get(BookingStatus.EXPIRED, 0),
            "unresolved_conflicts": open_conflicts,
            "utilization_pct": round(100 * total_used / total_cap, 1) if total_cap else 0.0,
        },
        "engineers_on_leave_today": [{"resource": r.display_name, "engineer_name": r.engineer_name} for r in on_leave],
        "charts": {
            "monthly_utilization": [
                {"month": mm.strftime("%Y-%m"), "used_days": used_by_month[mm], "capacity_days": cap_by_month[mm],
                 "utilization_pct": round(100 * used_by_month[mm] / cap_by_month[mm], 1) if cap_by_month[mm] else 0.0}
                for mm in months],
            "activity_distribution": [{"activity": k, "count": v} for k, v in activity_counts.most_common()],
            "status_distribution": [{"status": s, "label": BookingStatus.LABELS[s], "count": status_counts.get(s, 0)}
                                    for s in BookingStatus.ALL],
            "resource_allocation": [
                {"resource": r.display_name, "engineer_name": r.engineer_name, "booked_days": used_by_resource[r.id],
                 "capacity_days": cap_by_resource[r.id], "is_active": r.is_active,
                 "utilization_pct": round(100 * used_by_resource[r.id] / cap_by_resource[r.id], 1) if cap_by_resource[r.id] else 0.0}
                for r in resources],
            "monthly_volume": [{"month": mm.strftime("%Y-%m"), "count": volume_by_month[mm]} for mm in months],
        },
        "upcoming_bookings": [booking_admin_out(b) for b in upcoming],
        "pending_bookings": [booking_admin_out(b) for b in pending],
        "upcoming_holidays": [{"date": h.holiday_date.isoformat(), "name": h.name} for h in upcoming_holidays],
    }


EXPORT_COLUMNS = [
    ("Booking ID", lambda b: str(b.id)), ("Application Name", lambda b: b.application_name),
    ("Application Version", lambda b: b.application_version), ("Activity Type", lambda b: b.activity_name_snapshot),
    ("Duration (working days)", lambda b: b.duration_days), ("PCI DSS Scope", lambda b: "Yes" if b.pci_dss_scope else "No"),
    ("Resource", lambda b: b.resource.display_name), ("Engineer", lambda b: b.resource.engineer_name),
    ("Start Date", lambda b: b.start_date.isoformat()), ("End Date", lambda b: b.end_date.isoformat()),
    ("Status", lambda b: BookingStatus.LABELS[b.status]), ("POC Name", lambda b: b.poc_name),
    ("POC Email", lambda b: b.poc_email), ("Requester", lambda b: b.requester.email),
    ("Submitted At", lambda b: b.submitted_at.isoformat()), ("Force Allocated", lambda b: "Yes" if b.is_force_allocated else "No"),
    ("Needs Review", lambda b: "Yes" if b.needs_review else "No"), ("Rejection Reason", lambda b: b.rejection_reason or ""),
    ("Cancellation Reason", lambda b: b.cancellation_reason or ""),
]


def _safe_cell(v):
    """Neutralise spreadsheet formula injection (CSV/Excel injection)."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


@router.get("/reports/bookings.{fmt}")
def export_bookings(fmt: str, status: str | None = None, start: date | None = None, end: date | None = None,
                    resource_id: str | None = None, limit: int = Query(10000, le=50000), db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    if fmt not in ("csv", "xlsx"):
        raise bad_request("Format must be csv or xlsx.")
    q = select(Booking)
    if status:
        q = q.where(Booking.status == status)
    if start:
        q = q.where(Booking.end_date >= start)
    if end:
        q = q.where(Booking.start_date <= end)
    if resource_id:
        q = q.where(Booking.resource_id == resource_id)
    rows = db.scalars(q.order_by(Booking.start_date).limit(limit)).unique().all()
    audit.record(db, "report.exported", admin, entity_type="report", entity_id=f"bookings.{fmt}",
                 new={"rows": len(rows), "status": status, "start": start, "end": end})
    commit(db)
    header = [c for c, _ in EXPORT_COLUMNS]
    data = [[_safe_cell(fn(b)) for _, fn in EXPORT_COLUMNS] for b in rows]
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(data)
        return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="bookings.csv"'})
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Bookings"
    ws.append(header)
    for row in data:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="bookings.xlsx"'})
