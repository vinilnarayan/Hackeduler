"""Backend-authoritative availability service.

Every booking decision (preview, submission, approval, reschedule, admin edit)
goes through this module. The frontend never computes end dates or availability
on its own; it only renders what this service returns.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import (
    ActivityType,
    Booking,
    BookingResourceLock,
    BookingStatus,
    Holiday,
    LockStatus,
    ResourceLeave,
    SecurityResource,
)
from . import settings_service
from .calendar_engine import (
    SchedulingError,
    WorkCalendar,
    compute_work_dates,
    eligible_dates_between,
    expand_ranges,
    find_next_available_start,
)

UNAVAILABLE_MESSAGE = (
    "The selected resource is no longer available for the requested dates. "
    "Please select another resource or date."
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def working_weekdays(db: Session) -> frozenset[int]:
    return frozenset(settings_service.get_setting(db, "working_weekdays"))


def load_holidays(db: Session, start: date, end: date) -> dict[date, str]:
    rows = db.execute(select(Holiday.holiday_date, Holiday.name).where(Holiday.holiday_date.between(start, end))).all()
    return {d: n for d, n in rows}


def load_leave_dates(db: Session, resource_ids: list[uuid.UUID], start: date, end: date) -> dict[uuid.UUID, frozenset[date]]:
    rows = db.execute(
        select(ResourceLeave.resource_id, ResourceLeave.start_date, ResourceLeave.end_date).where(
            ResourceLeave.resource_id.in_(resource_ids),
            ResourceLeave.status == "active",
            ResourceLeave.start_date <= end,
            ResourceLeave.end_date >= start,
        )
    ).all()
    grouped: dict[uuid.UUID, list[tuple[date, date]]] = defaultdict(list)
    for rid, s, e in rows:
        grouped[rid].append((s, e))
    return {rid: expand_ranges(grouped.get(rid, [])) for rid in resource_ids}


def build_calendar(db: Session, resource_id: uuid.UUID, start: date, end: date) -> WorkCalendar:
    return WorkCalendar(
        holidays=load_holidays(db, start, end),
        leave_dates=load_leave_dates(db, [resource_id], start, end)[resource_id],
        working_weekdays=working_weekdays(db),
    )


def active_lock_clause(db: Session):
    """SQL predicate for locks that currently hold a reservation.

    Pending locks past their expiry are treated as released (even before the
    background job physically releases them) when expiry is enabled.
    """
    base = BookingResourceLock.lock_status.in_(LockStatus.ACTIVE)
    if settings_service.get_setting(db, "pending_expiry_enabled"):
        return and_(
            base,
            or_(
                BookingResourceLock.lock_status == LockStatus.CONFIRMED,
                BookingResourceLock.expires_at.is_(None),
                BookingResourceLock.expires_at > now_utc(),
            ),
        )
    return base


def occupied_map(
    db: Session, resource_id: uuid.UUID, start: date, end: date, exclude_booking_id: uuid.UUID | None = None
) -> dict[date, list[tuple[uuid.UUID, str]]]:
    q = select(BookingResourceLock.work_date, BookingResourceLock.booking_id, BookingResourceLock.lock_status).where(
        BookingResourceLock.resource_id == resource_id,
        BookingResourceLock.work_date.between(start, end),
        active_lock_clause(db),
    )
    if exclude_booking_id is not None:
        q = q.where(BookingResourceLock.booking_id != exclude_booking_id)
    out: dict[date, list[tuple[uuid.UUID, str]]] = defaultdict(list)
    for d, bid, st in db.execute(q).all():
        out[d].append((bid, st))
    return out


@dataclass
class ScheduleIssue:
    type: str  # overlapping_booking | non_working_start | inactive_resource | inactive_activity | holiday | leave
    message: str
    booking_ids: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)


@dataclass
class SchedulePlan:
    resource: SecurityResource
    start_date: date
    duration_days: int
    work_dates: list[date]
    issues: list[ScheduleIssue]
    calendar: WorkCalendar
    conflicting_booking_ids: list[uuid.UUID] = field(default_factory=list)
    conflict_dates: list[date] = field(default_factory=list)

    @property
    def end_date(self) -> date | None:
        return self.work_dates[-1] if self.work_dates else None

    @property
    def ok(self) -> bool:
        return not self.issues


def horizon_end(start: date, duration: int) -> date:
    # generous window: durations are working days; allow weekends + holidays + leave
    return start + timedelta(days=max(60, duration * 3 + 60))


def plan_schedule(
    db: Session,
    resource: SecurityResource,
    start: date,
    duration_days: int,
    *,
    exclude_booking_id: uuid.UUID | None = None,
    explicit_end_date: date | None = None,
    allow_ineligible_start: bool = False,
) -> SchedulePlan:
    """Compute the working dates for a proposed allocation and list every rule it violates.

    ``explicit_end_date`` (admin only) reserves all eligible dates in
    [start, explicit_end_date] instead of counting ``duration_days``.
    """
    end_window = max(horizon_end(start, duration_days), explicit_end_date or start)
    cal = build_calendar(db, resource.id, start, end_window)
    issues: list[ScheduleIssue] = []

    if not resource.is_active:
        issues.append(ScheduleIssue("inactive_resource", f"{resource.display_name} is inactive and cannot accept new allocations."))

    def dates_for(allow_bad_start: bool) -> list[date]:
        if explicit_end_date is None:
            return compute_work_dates(cal, start, duration_days, allow_ineligible_start=allow_bad_start)
        if explicit_end_date < start:
            raise SchedulingError("invalid_range", "End date must be on or after the start date.")
        bad_start = cal.non_working_reason(start) is not None
        if bad_start and not allow_bad_start:
            compute_work_dates(cal, start, 1)  # raises a descriptive non_working_start error
        dates = ([start] if bad_start else []) + eligible_dates_between(cal, start, explicit_end_date)
        if not dates:
            raise SchedulingError("invalid_range", "The selected range contains no working days for this resource.")
        return dates

    try:
        work_dates = dates_for(allow_ineligible_start)
    except SchedulingError as e:
        if e.code != "non_working_start":
            raise
        issues.append(ScheduleIssue("non_working_start", e.message, dates=[start.isoformat()]))
        # compute the plan as Force Allocate would, so admins can see the impact
        work_dates = dates_for(True)

    if resource.is_active and resource.inactive_from and work_dates and work_dates[-1] >= resource.inactive_from:
        blocked = [d for d in work_dates if d >= resource.inactive_from]
        issues.append(ScheduleIssue(
            "inactive_resource",
            f"{resource.display_name} is unavailable from {resource.inactive_from.strftime('%d %b %Y')}. This booking would run "
            f"until {work_dates[-1].strftime('%d %b %Y')}. Choose an earlier start date or another resource.",
            dates=[d.isoformat() for d in blocked],
        ))

    conflicting: list[uuid.UUID] = []
    conflict_dates: list[date] = []
    if work_dates:
        occ = occupied_map(db, resource.id, work_dates[0], work_dates[-1], exclude_booking_id)
        for d in work_dates:
            for bid, _st in occ.get(d, []):
                if bid not in conflicting:
                    conflicting.append(bid)
                if d not in conflict_dates:
                    conflict_dates.append(d)
    if conflicting:
        issues.append(
            ScheduleIssue(
                "overlapping_booking",
                "The requested dates overlap an existing pending reservation or approved booking for this resource.",
                booking_ids=[str(b) for b in conflicting],
                dates=[d.isoformat() for d in conflict_dates],
            )
        )
    return SchedulePlan(
        resource=resource,
        start_date=start,
        duration_days=len(work_dates) if explicit_end_date is not None else duration_days,
        work_dates=work_dates,
        issues=issues,
        calendar=cal,
        conflicting_booking_ids=conflicting,
        conflict_dates=conflict_dates,
    )


def suggest_next_start(db: Session, resource: SecurityResource, duration: int, after: date, exclude_booking_id=None) -> date | None:
    if not resource.is_active or (resource.inactive_from and resource.inactive_from <= after):
        return None
    window_end = after + timedelta(days=180 + duration * 3 + 60)
    cal = build_calendar(db, resource.id, after, window_end)
    occ = set(occupied_map(db, resource.id, after, window_end, exclude_booking_id).keys())
    if resource.inactive_from:  # the booking must finish before the resource becomes inactive
        d = resource.inactive_from
        while d <= window_end:
            occ.add(d)
            d += timedelta(days=1)
    return find_next_available_start(cal, duration, occ, after, horizon_days=180)


def alternative_resources(db: Session, exclude_resource_id: uuid.UUID, start: date, duration: int) -> list[SecurityResource]:
    out = []
    for r in db.scalars(select(SecurityResource).where(SecurityResource.is_active.is_(True), SecurityResource.deleted_at.is_(None)).order_by(SecurityResource.sequence_no)):
        if r.id == exclude_resource_id:
            continue
        try:
            p = plan_schedule(db, r, start, duration)
        except SchedulingError:
            continue
        if p.ok:
            out.append(r)
    return out


def total_duration(activity: ActivityType, additional_days: int) -> int:
    if additional_days < 0:
        raise SchedulingError("invalid_duration", "Additional days cannot be negative.")
    if additional_days and not activity.allow_additional_days:
        raise SchedulingError("invalid_duration", "This activity type does not allow additional days.")
    if additional_days > activity.max_additional_days:
        raise SchedulingError("invalid_duration", f"A maximum of {activity.max_additional_days} additional day(s) is allowed.")
    return activity.base_duration_days + additional_days


# --------------------------------------------------------------------------------------
# Calendar grid
# --------------------------------------------------------------------------------------

def calendar_grid(
    db: Session,
    start: date,
    end: date,
    *,
    viewer_id: uuid.UUID | None,
    admin: bool,
    activity_duration: int | None = None,
) -> dict:
    """Per-resource, per-day availability states.

    States: available (green), limited (yellow), reserved (blue, pending),
    occupied (red, approved/completed), non_working (grey: weekend|holiday|leave),
    inactive (grey). When ``activity_duration`` is supplied, an otherwise free day
    on which a booking of that length could NOT start is marked ``limited``.
    """
    if (end - start).days > 186:
        raise SchedulingError("range_too_large", "Calendar range is limited to ~6 months.")
    resources = list(db.scalars(select(SecurityResource).where(SecurityResource.deleted_at.is_(None)).order_by(SecurityResource.sequence_no)))
    rids = [r.id for r in resources]
    look_ahead = end + timedelta(days=(activity_duration or 0) * 3 + 30)
    holidays = load_holidays(db, start, look_ahead)
    leaves = load_leave_dates(db, rids, start, look_ahead) if rids else {}
    wk = working_weekdays(db)

    lock_rows = db.execute(
        select(
            BookingResourceLock.resource_id,
            BookingResourceLock.work_date,
            BookingResourceLock.lock_status,
            BookingResourceLock.is_forced,
            Booking.id,
            Booking.requester_id,
            Booking.status,
            Booking.application_name,
            Booking.activity_name_snapshot,
        )
        .join(Booking, Booking.id == BookingResourceLock.booking_id)
        .where(BookingResourceLock.work_date.between(start, look_ahead), active_lock_clause(db))
    ).all()
    occ: dict[tuple[uuid.UUID, date], list] = defaultdict(list)
    for row in lock_rows:
        occ[(row.resource_id, row.work_date)].append(row)

    out_resources = []
    for r in resources:
        cal = WorkCalendar(holidays=holidays, leave_dates=leaves.get(r.id, frozenset()), working_weekdays=wk)
        occupied_dates = {d for (rid, d) in occ.keys() if rid == r.id}
        days = []
        d = start
        while d <= end:
            cell: dict = {"date": d.isoformat()}
            rows = occ.get((r.id, d), [])
            reason = cal.non_working_reason(d)
            if rows:
                confirmed = any(x.lock_status == LockStatus.CONFIRMED for x in rows)
                cell["state"] = "occupied" if confirmed else "reserved"
                mine = [x for x in rows if viewer_id and x.requester_id == viewer_id]
                cell["mine"] = bool(mine)
                if admin:
                    cell["bookings"] = [
                        {"id": str(x.id), "status": x.status, "application_name": x.application_name,
                         "activity": x.activity_name_snapshot, "forced": x.is_forced}
                        for x in rows
                    ]
                    cell["conflict"] = len(rows) > 1
                elif mine:
                    cell["bookings"] = [{"id": str(x.id), "status": x.status, "application_name": x.application_name} for x in mine]
            elif r.inactive_on(d):
                cell["state"] = "inactive"
                cell["reason"] = "inactive"
            elif reason:
                cell["state"] = "non_working"
                cell["reason"] = reason
                if reason == "holiday":
                    cell["label"] = holidays.get(d)
            else:
                cell["state"] = "available"
                if activity_duration:
                    try:
                        wd = compute_work_dates(cal, d, activity_duration)
                        if occupied_dates.intersection(wd) or (r.inactive_from and wd[-1] >= r.inactive_from):
                            cell["state"] = "limited"
                    except SchedulingError:
                        cell["state"] = "limited"
            days.append(cell)
            d += timedelta(days=1)
        res = {"id": str(r.id), "code": r.code, "display_name": r.display_name, "is_active": r.is_active,
               "inactive_from": r.inactive_from.isoformat() if r.inactive_from else None, "days": days}
        if admin:
            res["engineer_name"] = r.engineer_name
        out_resources.append(res)

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "holidays": [{"date": k.isoformat(), "name": v} for k, v in sorted(holidays.items()) if k <= end],
        "resources": out_resources,
    }


def booking_is_active(b: Booking) -> bool:
    return b.status in BookingStatus.ACTIVE
