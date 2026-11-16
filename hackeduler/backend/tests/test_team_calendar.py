"""Admin Team Calendar: every resource's bookings, leave and holidays by day."""
from .conftest import MON, booking_payload


def _days(cal):
    return {d["date"]: d for d in cal["days"]}


def test_shows_every_resources_activity_leave_and_holidays(admin, req1, data):
    admin.post("/api/admin/holidays", json={"name": "Spring Fest", "holiday_date": "2027-03-26"})
    b0 = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=3)).json()
    b1 = admin.post("/api/admin/bookings", json=booking_payload(data, 1, start=MON, duration_days=2, application_name="Billing")).json()
    pending = req1.post("/api/bookings", json=booking_payload(data, 2, start=MON)).json()
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][0].id), "start_date": "2027-03-15", "end_date": "2027-03-16", "leave_type": "Annual leave"})
    cal = admin.get("/api/admin/team-calendar?month=2027-03").json()
    days = _days(cal)
    mon = days["2027-03-01"]["entries"]
    assert [e["resource_name"] for e in mon] == ["Resource 01", "Resource 02", "Resource 03"]
    assert {e["application_name"] for e in mon} == {"Customer Portal", "Billing"}
    e0 = next(e for e in mon if e["booking_id"] == b0["id"])
    assert e0["activity_name"] and e0["engineer_name"] and e0["status"] == "approved" and not e0["tentative"]
    ep = next(e for e in mon if e["booking_id"] == pending["id"])
    assert ep["tentative"] and ep["status"] == "pending_approval"
    ids = {e["booking_id"] for e in days["2027-03-03"]["entries"]}
    assert b0["id"] in ids and b1["id"] not in ids                                           # b1 ended on the 2nd
    assert [l["resource_name"] for l in days["2027-03-15"]["leaves"]] == ["Resource 01"] and days["2027-03-15"]["leaves"][0]["leave_type"] == "Annual leave"
    assert days["2027-03-26"]["holiday"] == "Spring Fest"
    assert days["2027-03-06"]["weekend"] and not days["2027-03-02"]["weekend"]
    assert cal["summary"]["holidays"] == 1 and cal["summary"]["leave_days"] == 2 and len(cal["resources"]) == 3


def test_grid_shape_and_resource_filter(admin, data):
    admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=2))
    admin.post("/api/admin/bookings", json=booking_payload(data, 1, start=MON, duration_days=2))
    cal = admin.get(f"/api/admin/team-calendar?month=2027-03&resource_id={data['resources'][1].id}").json()
    assert len(cal["days"]) % 7 == 0 and cal["days"][0]["date"] == "2027-03-01"
    assert [e["resource_name"] for e in _days(cal)["2027-03-01"]["entries"]] == ["Resource 02"]
    assert admin.get("/api/admin/team-calendar?month=2027-03&resource_id=00000000-0000-0000-0000-000000000001").status_code == 404


def test_cancelled_and_released_bookings_do_not_show(admin, data):
    b = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=2)).json()
    assert _days(admin.get("/api/admin/team-calendar?month=2027-03").json())["2027-03-01"]["entries"]
    r = admin.post(f"/api/admin/bookings/{b['id']}/cancel", json={"reason": "no longer needed"})
    assert r.status_code == 200, r.text
    assert _days(admin.get("/api/admin/team-calendar?month=2027-03").json())["2027-03-01"]["entries"] == []


def test_bad_month_and_access(admin, req1, data):
    for bad in ("2027-13", "2027-3", "x", "1990-01"):
        assert admin.get(f"/api/admin/team-calendar?month={bad}").status_code == 422
    assert req1.get("/api/admin/team-calendar?month=2027-03").status_code == 403
