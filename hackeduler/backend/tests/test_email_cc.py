"""Always-Cc recipients on every outgoing email (Admin -> Settings)."""
from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.models import EmailNotificationLog
from app.services import email_sender, initiation, settings_service

from .conftest import booking_payload


def _set_cc(admin, cc):
    r = admin.put("/api/admin/settings", json={"values": {"email_cc_recipients": cc}})
    assert r.status_code == 200, r.text


def _drain():
    db = SessionLocal()
    email_sender.process_outbox(db)
    db.close()
    return list(email_sender.SENT_MESSAGES)


def test_default_is_no_cc(req1, data):
    req1.post("/api/bookings", json=booking_payload(data))
    msgs = _drain()
    assert msgs and all(m["Cc"] is None for m in msgs)


def test_every_email_gets_the_configured_cc(admin, req1, data):
    _set_cc(admin, ["Security-Team@example.com", "lead@example.com", "lead@example.com"])
    req1.post("/api/bookings", json=booking_payload(data))
    msgs = _drain()
    assert msgs
    for m in msgs:
        assert m["Cc"] == "Security-Team@example.com, lead@example.com"


def test_recipient_is_not_copied_on_their_own_email(admin, req1, data):
    _set_cc(admin, ["offsec-admins@example.com", "other@example.com"])       # offsec-admins is also an admin recipient
    req1.post("/api/bookings", json=booking_payload(data))
    msgs = _drain()
    to_admin = [m for m in msgs if m["To"] == "offsec-admins@example.com"]
    assert to_admin and all(m["Cc"] == "other@example.com" for m in to_admin)
    assert all("offsec-admins@example.com" in m["Cc"] for m in msgs if m not in to_admin)


def test_initiation_email_is_copied(admin, data, monkeypatch):
    _set_cc(admin, ["pm@example.com"])
    monkeypatch.setattr(settings_service, "org_today", lambda db: date(2027, 2, 1))
    admin.post("/api/admin/bookings", json=booking_payload(data))
    monkeypatch.setattr(settings_service, "org_today", lambda db: date(2027, 2, 22))
    db = SessionLocal()
    assert initiation.send_due(db) == 1
    db.commit()
    subjects = {r.subject for r in db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == "activity_initiation_poc"))}
    email_sender.process_outbox(db)
    db.close()
    ini = [m for m in email_sender.SENT_MESSAGES if m["Subject"] in subjects]
    assert ini and all(m["Cc"] == "eng1@offsec.local, pm@example.com" for m in ini)     # assigned engineer, then the settings Cc


def test_cc_setting_is_validated(admin):
    for bad in (["not-an-email"], ["a@b.co\nBcc: x@y.zz"], ["a@b.co, c@d.co"], ["a@example.com"] * 11, "a@example.com"):
        assert admin.put("/api/admin/settings", json={"values": {"email_cc_recipients": bad}}).status_code == 422, bad
    _set_cc(admin, [])
    assert admin.get("/api/admin/settings").json()["values"]["email_cc_recipients"] == []


def test_ses_recipients_include_cc(admin, req1, data):
    import email.utils
    _set_cc(admin, ["pm@example.com"])
    req1.post("/api/bookings", json=booking_payload(data))
    m = _drain()[0]
    addrs = [a for _, a in email.utils.getaddresses(m.get_all("To", []) + m.get_all("Cc", []))]
    assert "pm@example.com" in addrs and m["To"] in addrs


def test_resource_name_variable_is_available_and_rendered(admin, data):
    assert "Resource Name" in admin.get("/api/admin/email-templates/variables").json()
    b = admin.post("/api/admin/bookings", json=booking_payload(data)).json()
    db = SessionLocal()
    try:
        from app.models import Booking
        from app.services import notifications
        ctx = notifications.booking_context(db.get(Booking, b["id"]))
        assert ctx["Resource Name"] == "Resource 01" == ctx["Resource ID"]
        assert notifications.render("Resource: {{Resource Name}}", ctx) == "Resource: Resource 01"
    finally:
        db.close()
