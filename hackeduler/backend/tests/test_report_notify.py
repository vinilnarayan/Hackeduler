"""Saving a shared report can inform the POC: To POC + requester, Cc Admin notification recipients + engineers."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, Booking, EmailNotificationLog, EmailTemplate

from .conftest import MON, PASSWORD, Api, booking_payload

URL = "https://contoso.sharepoint.com/sites/offsec/Reports/app_v1.pdf"
BODY = {"report_shared": True, "report_type": "V1", "report_url": URL, "report_comments": "3 high findings"}


def _setup(admin, data):
    b = admin.post("/api/admin/bookings", json=booking_payload(data, start=MON)).json()
    db = SessionLocal()
    bk = db.get(Booking, uuid.UUID(b["id"]))
    bk.requester_id, bk.source = data["users"]["req1"].id, "requester"
    db.commit()
    db.close()
    admin.post("/api/admin/users", json={"email": "eng1@test.local", "full_name": "Eng One", "password": PASSWORD,
                                         "role": "resource", "resource_id": str(data["resources"][0].id)})
    return b, Api("eng1@test.local")


def _mails(bid):
    db = SessionLocal()
    rows = list(db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.booking_id == uuid.UUID(bid),
                                                              EmailNotificationLog.template_key == "report_shared_poc")))
    db.close()
    return rows


def test_yes_sends_one_email_with_recipients_subject_and_link(admin, data):
    b, eng = _setup(admin, data)
    r = eng.put(f"/api/resource/bookings/{b['id']}/report", json={**BODY, "notify_poc": True})
    assert r.status_code == 200, r.text
    (m,) = _mails(b["id"])
    assert "req1@test.local" in m.recipient.lower() or data["users"]["req1"].email in m.recipient
    assert m.subject == f"[Hackeduler] Penetration Test Report – {b['application_name']} | {b['id']}"
    assert "offsec-admins@example.com" in m.cc and "eng1@offsec.local" in m.cc   # Admin notification recipients + engineer
    assert URL in m.body and URL in m.body_html and "3 high findings" in m.body and "Eng One" in m.body
    assert "<table" in m.body_html


def test_no_saves_but_sends_nothing(admin, data):
    b, eng = _setup(admin, data)
    r = eng.put(f"/api/resource/bookings/{b['id']}/report", json=BODY)     # notify_poc defaults to false
    assert r.status_code == 200 and r.json()["report_shared"] is True
    assert _mails(b["id"]) == []
    r = eng.put(f"/api/resource/bookings/{b['id']}/report", json={**BODY, "notify_poc": False})
    assert _mails(b["id"]) == []


def test_not_shared_never_sends_and_admin_can_notify(admin, data):
    b, _ = _setup(admin, data)
    assert admin.put(f"/api/admin/bookings/{b['id']}/report", json={"report_shared": False, "notify_poc": True}).status_code == 200
    assert _mails(b["id"]) == []
    assert admin.put(f"/api/admin/bookings/{b['id']}/report", json={**BODY, "notify_poc": True}).status_code == 200
    (m,) = _mails(b["id"])
    assert "offsec-admins@example.com" in (m.cc or "")


def test_template_is_editable_and_audited(admin, data):
    b, eng = _setup(admin, data)
    keys = [t["key"] for t in admin.get("/api/admin/email-templates").json()]
    assert "report_shared_poc" in keys
    t = [t for t in admin.get("/api/admin/email-templates").json() if t["key"] == "report_shared_poc"][0]
    assert t["body_format"] == "html"
    r = admin.put("/api/admin/email-templates/report_shared_poc",
                  json={"subject_template": "Report {{Report Link}} | {{Booking ID}}", "body_template": "<p>Hi {{POC Name}} {{Report Link}}</p>"})
    assert r.status_code == 200, r.text
    eng.put(f"/api/resource/bookings/{b['id']}/report", json={**BODY, "notify_poc": True})
    (m,) = _mails(b["id"])
    assert m.subject.startswith("Report https://contoso")
    db = SessionLocal()
    a = db.scalars(select(AuditLog).where(AuditLog.action == "booking.report_updated")).all()
    db.close()
    assert any((x.new_value or {}).get("poc_notified") for x in a)
