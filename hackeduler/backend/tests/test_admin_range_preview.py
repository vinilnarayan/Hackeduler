"""Manual allocation: the 'actual' working days of an explicit start-end range."""
from .conftest import MON, booking_payload

RANGE = "/api/admin/availability/range"


def _q(data, i=0, **kw):
    return {"resource_id": str(data["resources"][i].id), "start_date": "2027-03-01", "end_date": "2027-03-08", **kw}


def test_weekends_excluded(admin, data):
    r = admin.post(RANGE, json=_q(data)).json()
    assert r["calendar_days"] == 8 and r["working_days"] == 6 and r["skipped"]["weekend"] == 2
    assert r["available"] and r["leave_considered"] and "2027-03-06" not in r["work_dates"]


def test_holidays_and_leave_excluded(admin, data):
    admin.post("/api/admin/holidays", json={"name": "Spring Fest", "holiday_date": "2027-03-03"})
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][0].id), "start_date": "2027-03-04", "end_date": "2027-03-04", "leave_type": "Annual leave"})
    r = admin.post(RANGE, json=_q(data)).json()
    assert r["working_days"] == 4 and r["skipped"] == {"weekend": 2, "holiday": 1, "leave": 1}
    assert {s["reason"] for s in r["skipped_dates"]} == {"weekend", "holiday", "leave"}
    assert next(s for s in r["skipped_dates"] if s["reason"] == "holiday")["label"] == "Spring Fest"
    other = admin.post(RANGE, json=_q(data, 1)).json()                                      # leave is per resource
    assert other["working_days"] == 5 and other["skipped"]["leave"] == 0


def test_without_resource_ignores_leave(admin, data):
    admin.post("/api/admin/holidays", json={"name": "Spring Fest", "holiday_date": "2027-03-03"})
    r = admin.post(RANGE, json={"start_date": "2027-03-01", "end_date": "2027-03-08"}).json()
    assert r["working_days"] == 5 and not r["leave_considered"] and r["available"]


def test_conflict_is_reported(admin, data):
    admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=2))
    r = admin.post(RANGE, json=_q(data)).json()
    assert not r["available"] and r["issues"]


def test_validation_and_access(admin, req1, data):
    assert admin.post(RANGE, json=_q(data, end_date="2027-02-28")).status_code == 422
    assert admin.post(RANGE, json=_q(data, end_date="2029-03-08")).status_code == 422
    assert admin.post(RANGE, json={"start_date": "2027-03-06", "end_date": "2027-03-07"}).json()["working_days"] == 0
    assert admin.post(RANGE, json=_q(data, resource_id="00000000-0000-0000-0000-000000000001")).status_code == 404
    assert req1.post(RANGE, json=_q(data)).status_code == 403
