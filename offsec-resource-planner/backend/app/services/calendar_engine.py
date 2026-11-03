"""Pure, side-effect-free working-day arithmetic.

This module contains no database access so it can be unit tested exhaustively.
The DB-backed availability service builds a ``WorkCalendar`` for a resource and
delegates all date arithmetic here.

Definitions
-----------
* A date is *eligible* for a resource when it is a configured working weekday
  (default Mon-Fri), is not an organisation holiday and is not a leave day of
  that resource.
* A booking of N working days starting on S reserves exactly the first N
  eligible dates on or after S. S itself must be eligible. The *end date* is the
  last reserved date. Non-working dates inside [S, end] are NOT reserved.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

DEFAULT_WORKING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})  # Monday=0 ... Friday=4
MAX_SPAN_DAYS = 730  # safety bound for pathological calendars


class SchedulingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class WorkCalendar:
    holidays: dict[date, str] = field(default_factory=dict)
    leave_dates: frozenset[date] = frozenset()
    working_weekdays: frozenset[int] = DEFAULT_WORKING_WEEKDAYS

    def non_working_reason(self, d: date) -> str | None:
        """Return 'weekend' | 'holiday' | 'leave' or None when the date is eligible."""
        if d.weekday() not in self.working_weekdays:
            return "weekend"
        if d in self.holidays:
            return "holiday"
        if d in self.leave_dates:
            return "leave"
        return None

    def is_eligible(self, d: date) -> bool:
        return self.non_working_reason(d) is None


def expand_ranges(ranges: Iterable[tuple[date, date]]) -> frozenset[date]:
    out: set[date] = set()
    for start, end in ranges:
        d = start
        while d <= end:
            out.add(d)
            d += timedelta(days=1)
    return frozenset(out)


def compute_work_dates(cal: WorkCalendar, start: date, working_days: int, *, allow_ineligible_start: bool = False) -> list[date]:
    """Return the eligible working dates reserved by a booking.

    ``allow_ineligible_start`` is used ONLY for admin Force Allocate: the start
    date is reserved even though it is non-working; subsequent days are counted
    on eligible dates only.
    """
    if working_days <= 0:
        raise SchedulingError("invalid_duration", "Duration must be a positive number of working days.")
    reason = cal.non_working_reason(start)
    if reason and not allow_ineligible_start:
        raise SchedulingError("non_working_start", _start_message(reason, start, cal))
    dates: list[date] = []
    d = start
    if reason and allow_ineligible_start:
        dates.append(d)
        d += timedelta(days=1)
    limit = start + timedelta(days=MAX_SPAN_DAYS)
    while len(dates) < working_days:
        if d > limit:
            raise SchedulingError("calendar_exhausted", "Unable to fit the duration within a reasonable horizon.")
        if cal.is_eligible(d):
            dates.append(d)
        d += timedelta(days=1)
    return dates


def eligible_dates_between(cal: WorkCalendar, start: date, end: date) -> list[date]:
    out = []
    d = start
    while d <= end:
        if cal.is_eligible(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def next_eligible(cal: WorkCalendar, after: date, horizon_days: int = 366) -> date | None:
    d = after
    for _ in range(horizon_days):
        if cal.is_eligible(d):
            return d
        d += timedelta(days=1)
    return None


def find_next_available_start(
    cal: WorkCalendar,
    working_days: int,
    occupied: set[date],
    search_from: date,
    horizon_days: int = 180,
) -> date | None:
    """First eligible start >= search_from whose full work-date set avoids ``occupied``."""
    d = search_from
    end = search_from + timedelta(days=horizon_days)
    while d <= end:
        if cal.is_eligible(d) and d not in occupied:
            try:
                dates = compute_work_dates(cal, d, working_days)
            except SchedulingError:
                return None
            if not occupied.intersection(dates):
                return d
        d += timedelta(days=1)
    return None


def _start_message(reason: str, d: date, cal: WorkCalendar) -> str:
    if reason == "weekend":
        return f"{d.isoformat()} is a weekend / non-working day. Bookings must start on a working day."
    if reason == "holiday":
        return f"{d.isoformat()} is an organisation holiday ({cal.holidays.get(d)}). Bookings must start on a working day."
    return f"The selected resource is unavailable on {d.isoformat()} (leave). Please choose another date or resource."
