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


def _free(cal, d):
    return [f["resource_name"] for f in _days(cal)[d]["free"]]


def test_free_resources_are_listed_per_day(admin, data):
    admin.post("/api/admin/holidays", json={"name": "Spring Fest", "holiday_date": "2027-03-26"})
    assert admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=2)).status_code == 201      # R1: 1st-2nd
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][1].id), "start_date": "2027-03-02", "end_date": "2027-03-02", "leave_type": "Annual leave"})
    cal = admin.get("/api/admin/team-calendar?month=2027-03").json()
    assert _free(cal, "2027-03-01") == ["Resource 02", "Resource 03"]           # R1 booked
    assert _free(cal, "2027-03-02") == ["Resource 03"]                          # R1 booked, R2 on leave
    assert _free(cal, "2027-03-04") == ["Resource 01", "Resource 02", "Resource 03"]
    assert _free(cal, "2027-03-06") == [] and _free(cal, "2027-03-26") == []    # weekend / holiday: nobody is "free", it's a day off
    assert all(set(f) == {"resource_id", "resource_name", "engineer_name"} for f in _days(cal)["2027-03-04"]["free"])


def test_a_pending_hold_is_not_free_and_filter_limits_the_free_list(admin, req1, data):
    pending = req1.post("/api/bookings", json=booking_payload(data, 2, start=MON)).json()
    assert pending["id"]
    cal = admin.get("/api/admin/team-calendar?month=2027-03").json()
    assert "Resource 03" not in _free(cal, "2027-03-01")                         # on hold for a pending request
    one = admin.get(f"/api/admin/team-calendar?month=2027-03&resource_id={data['resources'][0].id}").json()
    assert _free(one, "2027-03-04") == ["Resource 01"]


def test_inactive_resources_are_not_free_from_their_inactive_date(admin, data):
    r = admin.patch(f"/api/admin/resources/{data['resources'][2].id}", json={"inactive_from": "2027-03-10", "reason": "Left"})
    assert r.status_code == 200, r.text
    cal = admin.get("/api/admin/team-calendar?month=2027-03").json()
    assert "Resource 03" in _free(cal, "2027-03-09") and "Resource 03" not in _free(cal, "2027-03-10")


def test_week_parameter_returns_just_that_week(admin, data):
    admin.post("/api/admin/holidays", json={"name": "Spring Fest", "holiday_date": "2027-03-04"})
    admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=3))
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][1].id), "start_date": "2027-03-03", "end_date": "2027-03-03"})
    cal = admin.get("/api/admin/team-calendar?week=2027-03-03").json()          # a Wednesday: the week starts on Monday 1 March
    assert [d["date"] for d in cal["days"]] == [f"2027-03-0{n}" for n in range(1, 8)]
    assert cal["week"] == "2027-03-01" and all(d["in_month"] for d in cal["days"])
    days = _days(cal)
    assert len(days["2027-03-01"]["entries"]) == 1 and days["2027-03-04"]["holiday"] == "Spring Fest"
    assert cal["summary"]["holidays"] == 1 and cal["summary"]["leave_days"] == 1 and cal["summary"]["booked_days"] == 3
    one = admin.get(f"/api/admin/team-calendar?week=2027-03-03&resource_id={data['resources'][0].id}").json()
    assert one["summary"]["leave_days"] == 0 and one["summary"]["booked_days"] == 3
    assert admin.get("/api/admin/team-calendar?month=2027-03").json()["week"] is None
    assert admin.get("/api/admin/team-calendar?week=1999-01-01").status_code == 422
    assert admin.get("/api/admin/team-calendar?week=nope").status_code == 422
