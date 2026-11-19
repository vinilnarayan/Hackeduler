"""Booking modified: when the POC list changes, only the people removed get the second email. Booking approved: the
engineers get ONE email."""
from app.db import SessionLocal
from app.services import email_sender

from .conftest import MON, booking_payload


def _updated():
    db = SessionLocal()
    email_sender.process_outbox(db)
    db.close()
    return [m for m in email_sender.SENT_MESSAGES if "Booking Updated" in (m["Subject"] or "")]


def _mk(admin, data, poc):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=2, poc_email=poc))
    assert r.status_code == 201, r.text
    email_sender.SENT_MESSAGES.clear()
    return r.json()


def test_overlapping_poc_gets_one_email_and_removed_poc_gets_one(admin, data):
    b = _mk(admin, data, "a@example.com, b@example.com")
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"reason": "x", "poc_email": "a@example.com, c@example.com"}).status_code == 200
    mails = _updated()
    to = sorted(m["To"] for m in mails)
    assert to == ["a@example.com, c@example.com", "b@example.com"]            # a is not emailed twice; b (removed) is told
    everyone = [x.strip() for m in mails for x in m["To"].split(",")]
    assert everyone.count("a@example.com") == 1


def test_no_second_email_when_nobody_was_removed(admin, data):
    b = _mk(admin, data, "a@example.com")
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"reason": "x", "poc_email": "a@example.com, c@example.com"}).status_code == 200
    assert [m["To"] for m in _updated()] == ["a@example.com, c@example.com"]


def test_removal_is_case_insensitive(admin, data):
    b = _mk(admin, data, "A@Example.com, b@example.com")
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"reason": "x", "poc_email": "a@example.com"}).status_code == 200
    assert sorted(m["To"] for m in _updated()) == ["a@example.com", "b@example.com"]
