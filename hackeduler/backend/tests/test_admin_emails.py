"""Emails to the admins: ONE message addressed To all admin notification recipients (not one email per admin)."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import EmailNotificationLog
from app.services import email_sender

from .conftest import booking_payload

ADMINS = ["admin1@example.com", "admin2@example.com", "Admin3@example.com", "admin1@example.com"]   # one duplicate


def _rows(key, booking_id):
    db = SessionLocal()
    try:
        rows = db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == key,
                                                             EmailNotificationLog.booking_id == booking_id)).all()
        return [(r.recipient, email_sender.build_message(db, r)["To"]) for r in rows]
    finally:
        db.close()


def test_new_request_goes_to_all_admins_in_one_email(req1, admin, data):
    assert admin.put("/api/admin/settings", json={"values": {"admin_notification_recipients": ADMINS}}).status_code == 200
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    rows = _rows("booking_submitted_admin", b["id"])
    assert len(rows) == 1                                                         # one email, not one per admin
    recipient, to_header = rows[0]
    assert recipient == "admin1@example.com, admin2@example.com, Admin3@example.com"   # de-duplicated, everyone visible
    assert to_header == recipient


def test_change_request_goes_to_all_admins_in_one_email(req1, admin, data):
    admin.put("/api/admin/settings", json={"values": {"admin_notification_recipients": ADMINS[:3]}})
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    assert req1.post(f"/api/bookings/{b['id']}/change-requests", json={"request_type": "cancel", "reason": "Release delayed"}).status_code == 201
    rows = _rows("change_request_admin", b["id"])
    assert len(rows) == 1 and rows[0][0].count("@") == 3


def test_single_admin(req1, admin, data):
    admin.put("/api/admin/settings", json={"values": {"admin_notification_recipients": ["only@example.com"]}})
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert [r[0] for r in _rows("booking_submitted_admin", b["id"])] == ["only@example.com"]


def test_no_admins_configured_sends_nothing_and_does_not_fail(req1, admin, data):
    admin.put("/api/admin/settings", json={"values": {"admin_notification_recipients": []}})
    r = req1.post("/api/bookings", json=booking_payload(data))
    assert r.status_code == 201, r.text
    assert _rows("booking_submitted_admin", r.json()["id"]) == []
