"""Unit tests for the pure working-day engine (acceptance criteria 4, 5, 6)."""
from datetime import date

import pytest

from app.services.calendar_engine import (
    SchedulingError,
    WorkCalendar,
    compute_work_dates,
    eligible_dates_between,
    expand_ranges,
    find_next_available_start,
)

MON = date(2027, 3, 1)


def test_eight_days_skip_weekend():
    dates = compute_work_dates(WorkCalendar(), MON, 8)
    assert dates[0] == MON
    assert dates[-1] == date(2027, 3, 10)  # Mon..Fri + Mon..Wed
    assert all(d.weekday() < 5 for d in dates)
    assert len(dates) == 8


def test_holiday_extends_end_date():
    cal = WorkCalendar(holidays={date(2027, 3, 3): "Holi"})
    dates = compute_work_dates(cal, MON, 8)
    assert date(2027, 3, 3) not in dates
    assert dates[-1] == date(2027, 3, 11)


def test_leave_extends_only_that_resource():
    cal_leave = WorkCalendar(leave_dates=expand_ranges([(date(2027, 3, 8), date(2027, 3, 9))]))
    assert compute_work_dates(cal_leave, MON, 8)[-1] == date(2027, 3, 12)
    assert compute_work_dates(WorkCalendar(), MON, 8)[-1] == date(2027, 3, 10)


def test_weekend_holiday_and_leave_combined():
    cal = WorkCalendar(holidays={date(2027, 3, 2): "H1"}, leave_dates=frozenset({date(2027, 3, 4)}))
    dates = compute_work_dates(cal, MON, 5)
    assert dates == [date(2027, 3, 1), date(2027, 3, 3), date(2027, 3, 5), date(2027, 3, 8), date(2027, 3, 9)]


@pytest.mark.parametrize("start,code_part", [
    (date(2027, 3, 6), "weekend"),            # Saturday
    (date(2027, 3, 7), "weekend"),            # Sunday
])
def test_cannot_start_on_weekend(start, code_part):
    with pytest.raises(SchedulingError) as e:
        compute_work_dates(WorkCalendar(), start, 3)
    assert e.value.code == "non_working_start"
    assert code_part in e.value.message


def test_cannot_start_on_holiday_or_leave():
    with pytest.raises(SchedulingError) as e:
        compute_work_dates(WorkCalendar(holidays={MON: "X"}), MON, 3)
    assert "holiday" in e.value.message
    with pytest.raises(SchedulingError) as e:
        compute_work_dates(WorkCalendar(leave_dates=frozenset({MON})), MON, 3)
    assert "leave" in e.value.message


def test_forced_ineligible_start():
    sat = date(2027, 3, 6)
    dates = compute_work_dates(WorkCalendar(), sat, 3, allow_ineligible_start=True)
    assert dates == [sat, date(2027, 3, 8), date(2027, 3, 9)]


def test_invalid_duration():
    with pytest.raises(SchedulingError):
        compute_work_dates(WorkCalendar(), MON, 0)


def test_custom_working_weekdays():
    cal = WorkCalendar(working_weekdays=frozenset({0, 1, 2, 3}))  # Mon-Thu
    assert compute_work_dates(cal, MON, 5)[-1] == date(2027, 3, 8)


def test_next_available_start_skips_occupied():
    occupied = set(compute_work_dates(WorkCalendar(), MON, 3))  # Mon-Wed
    nxt = find_next_available_start(WorkCalendar(), 2, occupied, MON)
    assert nxt == date(2027, 3, 4)  # Thu
    nxt5 = find_next_available_start(WorkCalendar(), 5, occupied, MON)
    assert nxt5 == date(2027, 3, 4)  # Thu, Fri, Mon, Tue, Wed - all free


def test_eligible_between():
    assert len(eligible_dates_between(WorkCalendar(), MON, date(2027, 3, 14))) == 10
