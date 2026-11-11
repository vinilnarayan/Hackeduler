"""A booking can list several POC emails; all of them are notified."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import EmailNotificationLog
from app.emailutil import normalize_poc_emails

from .conftest import booking_payload


def _recipients(key):
    db = SessionLocal()
    rows = db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == key)).all()
    out = sorted(r.recipient for r in rows)
    db.close()
    return out


def test_normalize():
    assert normalize_poc_emails("a@x.com; b@y.com ,  A@x.com\nc@z.com") == "a@x.com, b@y.com, c@z.com"
    for bad in ("", "nope", "a@x.com, nope", ",".join(f"u{i}@x.com" for i in range(11))):
        try:
            normalize_poc_emails(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_requester_booking_with_several_pocs_notifies_all(req1, admin, data):
    r = req1.post("/api/bookings", json=booking_payload(data, poc_email="one@example.com, two@example.com"))
    assert r.status_code == 201, r.text
    assert r.json()["poc_email"] == "one@example.com, two@example.com"
    admin.post(f"/api/admin/bookings/{r.json()['id']}/approve")
    got = _recipients("booking_approved_poc")
    assert "one@example.com" in got and "two@example.com" in got


def test_admin_booking_and_edit_with_several_pocs(admin, data):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, poc_email="a@example.com;b@example.com"))
    assert r.status_code == 201, r.text
    assert r.json()["poc_email"] == "a@example.com, b@example.com"
    assert set(_recipients("booking_approved_poc")) >= {"a@example.com", "b@example.com"}
    e = admin.patch(f"/api/admin/bookings/{r.json()['id']}", json={"poc_email": "c@example.com, d@example.com", "reason": "x"})
    assert e.status_code == 200 and e.json()["poc_email"] == "c@example.com, d@example.com"
    assert set(_recipients("booking_modified_poc")) >= {"a@example.com", "b@example.com"}


def test_invalid_poc_email_rejected(req1, data):
    assert req1.post("/api/bookings", json=booking_payload(data, poc_email="ok@example.com, bad")).status_code == 422


def test_search_by_version(admin, req1, data):
    admin.post("/api/admin/bookings", json=booking_payload(data, application_version="9.8.7-rc"))
    admin.post("/api/admin/bookings", json=booking_payload(data, resource_idx=1, application_version="1.0"))
    hit = admin.get("/api/admin/bookings?q=9.8.7").json()
    assert hit["total"] == 1 and hit["items"][0]["application_version"] == "9.8.7-rc"
    req1.post("/api/bookings", json=booking_payload(data, resource_idx=2, application_version="4.4.4"))
    mine = req1.get("/api/bookings/mine?q=4.4.4").json()
    assert len(mine) == 1 and mine[0]["application_version"] == "4.4.4"
