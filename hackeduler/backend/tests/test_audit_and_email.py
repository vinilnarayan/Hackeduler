"""Audit immutability (criteria 22-23) and email outbox behaviour (criteria 13-14, 26-27)."""
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db import SessionLocal, engine
from app.models import AuditLog, Booking, EmailNotificationLog
from app.services import email_sender, notifications

from .conftest import booking_payload


def test_audit_rows_cannot_be_updated_or_deleted(req1, data):
    req1.post("/api/bookings", json=booking_payload(data))
    for sql in ("UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs", "TRUNCATE audit_logs",
                "UPDATE booking_status_history SET to_status = 'approved'", "DELETE FROM booking_status_history"):
        with engine.connect() as c:
            with pytest.raises(DBAPIError) as e:
                c.execute(text(sql))
            assert "append-only" in str(e.value)
            c.rollback()
    db = SessionLocal()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "booking.submitted")) is not None
    db.close()


def test_no_api_to_modify_audit(admin):
    for m in ("put", "patch", "delete"):
        r = getattr(admin, m)("/api/admin/audit")
        assert r.status_code == 405
    from app.main import app

    for route in app.routes:
        if "/audit" in getattr(route, "path", ""):
            assert route.methods == {"GET"}


def test_audit_filters(admin, req1, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    r = admin.get(f"/api/admin/audit?booking_id={b['id']}").json()
    assert {i["action"] for i in r["items"]} == {"booking.submitted", "booking.approved"}
    assert admin.get("/api/admin/audit?action=approved").json()["total"] == 1
    assert admin.get("/api/admin/audit?actor=req1@").json()["total"] >= 1


def test_template_rendering_and_validation():
    out = notifications.render("Hi {{POC Name}} - {{ Booking ID }} {{Unknown}}", {"POC Name": "Jane", "Booking ID": "1"})
    assert out == "Hi Jane - 1 "
    with pytest.raises(ValueError):
        notifications.validate_template("x {{Evil}}", "body")
    with pytest.raises(ValueError):
        notifications.validate_template("line1\nBcc: x@y", "body")
    # content is never evaluated
    assert notifications.render("{{POC Name}}", {"POC Name": "{{Booking ID}} __import__('os')"}) == "{{Booking ID}} __import__('os')"


def test_default_templates_match_spec(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    db = SessionLocal()
    m = db.scalar(select(EmailNotificationLog).where(EmailNotificationLog.template_key == "booking_submitted_admin"))
    assert m.subject == f"[Hackeduler] New Booking Request – {b['id']}"
    assert "PCI DSS Scope: Yes" in m.body and "Resource: Resource 01" in m.body and "Secret Engineer" not in m.body
    db.close()


def test_outbox_delivers(req1, data):
    req1.post("/api/bookings", json=booking_payload(data))
    db = SessionLocal()
    stats = email_sender.process_outbox(db)
    db.close()
    assert stats["sent"] >= 1
    assert email_sender.SENT_MESSAGES[0]["Subject"].startswith("[Hackeduler] New Booking Request")


def test_email_failure_is_logged_retried_and_does_not_affect_booking(req1, admin, data, monkeypatch):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()

    def boom(db, msg):
        raise email_sender.EmailBackendError("SMTP connection refused")

    monkeypatch.setattr(email_sender, "deliver", boom)
    db = SessionLocal()
    stats = email_sender.process_outbox(db)
    assert stats["retry"] >= 1
    row = db.scalar(select(EmailNotificationLog).where(EmailNotificationLog.booking_id == uuid.UUID(b["id"])))
    assert row.status == "queued" and row.attempts == 1 and "refused" in row.last_error
    # exhaust retries
    for _ in range(10):
        db.execute(text("UPDATE email_notification_logs SET next_attempt_at = now() - interval '1 second' WHERE status='queued'"))
        db.commit()
        email_sender.process_outbox(db)
    db.expire_all()
    row = db.get(EmailNotificationLog, row.id)
    assert row.status == "failed" and row.attempts == row.max_attempts
    bk = db.get(Booking, uuid.UUID(b["id"]))
    assert bk.status == "pending_approval"  # booking untouched
    db.close()
    # admin can see the failure and requeue it
    logs = admin.get("/api/admin/email-logs?status=failed").json()
    assert logs and logs[0]["last_error"]
    assert admin.post(f"/api/admin/email-logs/{logs[0]['id']}/retry").json()["status"] == "queued"
    # approval still works while mail is down
    assert admin.post(f"/api/admin/bookings/{b['id']}/approve").status_code == 200


def test_template_admin_edit(admin):
    r = admin.put("/api/admin/email-templates/booking_approved_poc", json={"subject_template": "Approved {{Booking ID}} {{Bad}}"})
    assert r.status_code == 422
    r = admin.put("/api/admin/email-templates/booking_approved_poc", json={"subject_template": "Approved: {{Booking ID}}"})
    assert r.status_code == 200
    p = admin.post("/api/admin/email-templates/booking_approved_poc/preview", json={}).json()
    assert p["subject"] == "Approved: 550e8400-e29b-41d4-a716-446655440000"


def test_settings_never_expose_secrets(admin):
    body = admin.get("/api/admin/settings").text
    assert "smtp_password\"" not in body.replace("smtp_password_configured", "")
    r = admin.put("/api/admin/settings", json={"values": {"smtp_password": "x"}})
    assert r.status_code == 422
    r = admin.put("/api/admin/settings", json={"values": {"pending_expiry_hours": 0}})
    assert r.status_code == 422
    r = admin.put("/api/admin/settings", json={"values": {"pending_expiry_hours": 48}})
    assert r.status_code == 200 and r.json()["values"]["pending_expiry_hours"] == 48
