"""Month calendar for the resource (security engineer) dashboard."""
from datetime import date

from .conftest import MON, PASSWORD, Api, booking_payload


def _eng(admin, data, idx=0, email="eng1@test.local"):
    r = admin.post("/api/admin/users", json={"email": email, "full_name": "Eng", "password": PASSWORD,
                                             "role": "resource", "resource_id": str(data["resources"][idx].id)})
    assert r.status_code == 201, r.text
    return Api(email)


def _days(cal):
    return {d["date"]: d for d in cal["days"]}


def test_month_grid_is_whole_weeks_monday_first(admin, data):
    eng = _eng(admin, data)
    cal = eng.get("/api/resource/calendar?month=2027-03").json()
    assert cal["month"] == "2027-03" and cal["first_day"] == "2027-03-01" and cal["last_day"] == "2027-03-31"
    assert len(cal["days"]) % 7 == 0
    assert date.fromisoformat(cal["days"][0]["date"]).weekday() == 0 and date.fromisoformat(cal["days"][-1]["date"]).weekday() == 6
    days = _days(cal)
    assert days["2027-03-06"]["state"] == "weekend" and days["2027-03-07"]["state"] == "weekend"
    assert days["2027-03-02"]["state"] == "free"
    assert not days["2027-04-01"]["in_month"] if "2027-04-01" in days else True


def test_booked_leave_holiday_free_and_summary(admin, data):
    admin.post("/api/admin/holidays", json={"name": "Spring Fest", "holiday_date": "2027-03-26"})
    b = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=3)).json()
    eng = _eng(admin, data)
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][0].id), "start_date": "2027-03-15", "end_date": "2027-03-16", "leave_type": "Annual"})
    cal = eng.get("/api/resource/calendar?month=2027-03").json()
    days = _days(cal)
    booked = sorted(d for d, v in days.items() if v["state"] == "booked")
    assert booked == ["2027-03-01", "2027-03-02", "2027-03-03"]
    assert all(days[d]["booking_ids"] == [b["id"]] for d in booked)
    assert cal["bookings"][b["id"]]["application_name"] == "Customer Portal"
    assert days["2027-03-15"]["state"] == "leave" and days["2027-03-15"]["leave"]["leave_type"] == "Annual"
    assert days["2027-03-26"]["state"] == "holiday" and days["2027-03-26"]["holiday"] == "Spring Fest"
    s = cal["summary"]
    assert (s["booked"], s["leave"], s["holidays"]) == (3, 2, 1)
    # every working day is exactly one of booked / conflict / leave / tentative / free
    assert s["booked"] + s["conflicts"] + s["leave"] + s["tentative"] + s["free"] == s["working_days"] == 22
    assert s["free"] == 22 - 3 - 2


def test_leave_over_a_booked_day_is_a_conflict(admin, data):
    admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=3))
    eng = _eng(admin, data)
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][0].id), "start_date": "2027-03-02", "end_date": "2027-03-02"})
    cal = eng.get("/api/resource/calendar?month=2027-03").json()
    assert _days(cal)["2027-03-02"]["state"] == "conflict" and cal["summary"]["conflicts"] == 1 and cal["summary"]["booked"] == 2


def test_leave_on_a_weekend_is_not_counted_as_leave(admin, data):
    eng = _eng(admin, data)
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][0].id), "start_date": "2027-03-06", "end_date": "2027-03-07"})
    cal = eng.get("/api/resource/calendar?month=2027-03").json()
    assert _days(cal)["2027-03-06"]["state"] == "weekend" and cal["summary"]["leave"] == 0


def test_only_my_resource_is_shown_and_pending_holds_have_no_details(admin, req1, data):
    admin.post("/api/admin/bookings", json=booking_payload(data, 1, start=MON, duration_days=2))          # someone else's
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][1].id), "start_date": "2027-03-10", "end_date": "2027-03-11"})
    pend = req1.post("/api/bookings", json=booking_payload(data, 0, start=MON))
    assert pend.status_code == 201, pend.text
    eng = _eng(admin, data, idx=0)
    cal = eng.get("/api/resource/calendar?month=2027-03").json()
    days = _days(cal)
    assert cal["bookings"] == {} and cal["summary"]["leave"] == 0 and cal["summary"]["booked"] == 0
    assert days["2027-03-01"]["state"] == "tentative" and days["2027-03-01"]["booking_ids"] == []
    held = cal["summary"]["tentative"]
    assert held >= 2
    admin.post(f"/api/admin/bookings/{pend.json()['id']}/approve", json={})
    cal = eng.get("/api/resource/calendar?month=2027-03").json()
    assert cal["summary"]["booked"] == held and cal["summary"]["tentative"] == 0


def test_multi_resource_slice_shows_only_my_own_days(admin, data):
    r = admin.post("/api/admin/bookings", json=booking_payload(
        data, 0, start=MON, duration_days=5, additional_resource_ids=[str(data["resources"][1].id)]))
    assert r.status_code == 201, r.text
    eng2 = _eng(admin, data, idx=1, email="eng2@test.local")
    cal = eng2.get("/api/resource/calendar?month=2027-03").json()
    assert r.json()["id"] in cal["bookings"] and cal["summary"]["booked"] >= 1


def test_default_month_and_validation(admin, data):
    eng = _eng(admin, data)
    assert eng.get("/api/resource/calendar").json()["month"] == date.today().strftime("%Y-%m")
    for bad in ("2027-13", "2027-3", "abcd-ef", "1990-01", "2099-01"):
        assert eng.get(f"/api/resource/calendar?month={bad}").status_code == 422, bad


def test_calendar_is_resource_role_only(admin, req1, data):
    assert req1.get("/api/resource/calendar").status_code == 403
    assert admin.get("/api/resource/calendar").status_code == 403
