"""A resource marking leave inside an existing booking: the leave is saved, the booking keeps its dates."""
from .conftest import MON, booking_payload
from .test_resource_calendar import _days, _eng


def _book(admin, data, **kw):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=10, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def test_leave_inside_booking_keeps_booking_dates(admin, data):
    b = _book(admin, data)
    s, e, n = b["start_date"], b["end_date"], b["duration_days"]
    eng = _eng(admin, data)
    r = eng.post("/api/resource/leaves", json={"start_date": "2027-03-03", "end_date": "2027-03-03", "leave_type": "Casual leave"})
    assert r.status_code == 201, r.text
    after = admin.get(f"/api/admin/bookings/{b['id']}").json()["booking"]
    assert (after["start_date"], after["end_date"], after["duration_days"], after["status"]) == (s, e, n, b["status"])
    # leave is stored for the resource and shown on the calendar day
    assert [lv["start_date"] for lv in eng.get("/api/resource/leaves").json()] == ["2027-03-03"]
    day = _days(eng.get("/api/resource/calendar?month=2027-03").json())["2027-03-03"]
    assert day["leave"] and day["booking_ids"] == [b["id"]]
    # the booking's days are still reserved
    assert after.get("end_date") == e


def test_no_flag_conflict_or_email_for_resource_leave(admin, data):
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import BookingConflict, EmailNotificationLog
    b = _book(admin, data)
    db = SessionLocal()
    mails_before = db.scalar(select(func.count()).select_from(EmailNotificationLog))
    db.close()
    eng = _eng(admin, data)
    r = eng.post("/api/resource/leaves", json={"start_date": "2027-03-02", "end_date": "2027-03-04", "leave_type": "Annual leave"})
    assert r.status_code == 201 and r.json()["overlapping_bookings"] == 1
    item = next(i for i in admin.get("/api/admin/bookings").json()["items"] if i["id"] == b["id"])
    assert item["needs_review"] is False and item["open_conflicts"] == 0
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(BookingConflict)) == 0
    assert db.scalar(select(func.count()).select_from(EmailNotificationLog)) == mails_before
    db.close()
    # cancelling the leave does not touch the booking either
    lid = eng.get("/api/resource/leaves").json()[0]["id"]
    assert eng.delete(f"/api/resource/leaves/{lid}").status_code == 200
    item = next(i for i in admin.get("/api/admin/bookings").json()["items"] if i["id"] == b["id"])
    assert (item["start_date"], item["end_date"], item["needs_review"], item["open_conflicts"]) == (b["start_date"], b["end_date"], False, 0)


def test_admin_entered_leave_still_flags_for_review(admin, data):
    b = _book(admin, data)
    r = admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][0].id), "start_date": "2027-03-03", "end_date": "2027-03-03", "leave_type": "Annual leave"})
    assert r.status_code == 201 and b["id"] in [str(x) for x in r.json()["flagged_bookings"]]
