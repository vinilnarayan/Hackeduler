"""Calendar: days before today are flagged, excluded from the fit check and never offered as bookable."""
from datetime import date

import pytest

from app.services import settings_service

from .conftest import MON, booking_payload


@pytest.fixture
def today(monkeypatch):
    """Pretend today is Wed 2027-03-17 (organisation time)."""
    d = date(2027, 3, 17)
    monkeypatch.setattr(settings_service, "org_today", lambda db: d)
    return d


def _cells(cal, idx=0):
    return {c["date"]: c for c in cal["resources"][idx]["days"]}


@pytest.mark.parametrize("who,url", [("req1", "/api/calendar"), ("admin", "/api/admin/calendar")])
def test_past_days_are_flagged_and_future_days_are_not(who, url, admin, req1, data, today, request):
    api = request.getfixturevalue(who)
    cells = _cells(api.get(f"{url}?start=2027-03-08&end=2027-03-26").json())
    assert all(c.get("past") is True for d, c in cells.items() if d < "2027-03-17")
    assert all("past" not in c for d, c in cells.items() if d >= "2027-03-17")


@pytest.mark.parametrize("who,url", [("req1", "/api/calendar"), ("admin", "/api/admin/calendar")])
def test_fit_check_ignores_past_start_days(who, url, admin, req1, data, today, request):
    """An 8-day activity can't start on a day that has already gone, even if that stretch would be free/blocked."""
    api = request.getfixturevalue(who)
    r = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=date(2027, 3, 23), duration_days=3))   # blocks Tue 23rd..
    assert r.status_code == 201, r.text
    act = data["acts"][0]
    cal = api.get(f"{url}?start=2027-03-08&end=2027-03-31&activity_type_id={act.id}").json()
    cells = _cells(cal)
    # past working days: plain available (no yellow), flagged past
    assert cells["2027-03-10"]["state"] == "available" and cells["2027-03-10"]["past"]
    # future days are still fit-checked: starting on the 17th would run into the booking on the 23rd
    assert cells["2027-03-17"]["state"] == "limited"


def test_without_fit_check_nothing_is_limited_and_past_flag_still_present(req1, data, today):
    cells = _cells(req1.get("/api/calendar?start=2027-03-15&end=2027-03-19").json())
    assert {c["state"] for c in cells.values()} == {"available"} and cells["2027-03-16"]["past"] and "past" not in cells["2027-03-17"]


def test_past_booked_days_keep_their_state(admin, data, today):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=2))       # 2027-03-01..02
    assert r.status_code == 201, r.text
    cells = _cells(admin.get("/api/admin/calendar?start=2027-03-01&end=2027-03-05").json())
    assert cells["2027-03-01"]["state"] == "occupied" and cells["2027-03-01"]["past"]
