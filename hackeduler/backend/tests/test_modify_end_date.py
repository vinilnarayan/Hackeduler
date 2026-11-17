"""Admin modify: the end date of an existing booking can be extended or shortened."""
from datetime import date

from .conftest import MON, booking_payload


def _mk(admin, data, **kw):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=2, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def _patch(admin, b, **body):
    return admin.patch(f"/api/admin/bookings/{b['id']}", json={"reason": "adjust", **body})


def test_extend_end_date_skips_weekend_and_holiday(admin, data):
    b = _mk(admin, data)
    admin.post("/api/admin/holidays", json={"name": "Spring Fest", "holiday_date": "2027-03-09"})
    r = _patch(admin, b, end_date="2027-03-10")                       # Mon 1st .. Wed 10th
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["end_date"] == "2027-03-10" and out["start_date"] == "2027-03-01"
    assert out["duration_days"] == 7 and out["duration_overridden"] is True          # 8 weekdays minus the 9th


def test_shorten_end_date_releases_days(admin, data):
    b = _mk(admin, data)
    longer = _patch(admin, b, end_date="2027-03-05").json()
    assert longer["duration_days"] == 5
    r = _patch(admin, b, end_date="2027-03-03")
    assert r.status_code == 200 and r.json()["end_date"] == "2027-03-03" and r.json()["duration_days"] == 3
    # released days are free again
    other = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=date(2027, 3, 4), duration_days=1))
    assert other.status_code == 201, other.text


def test_end_before_start_rejected(admin, data):
    b = _mk(admin, data)
    assert _patch(admin, b, end_date="2027-02-26").status_code in (400, 422)
