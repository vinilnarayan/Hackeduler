"""Activity initiation email: schedule, once-only, reschedule, overrides, manual send, per-type content."""
from datetime import date

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import EmailNotificationLog
from app.services import initiation, settings_service

from .conftest import MON, booking_payload

KEY = "activity_initiation_poc"


def _today(monkeypatch, d: date):
    monkeypatch.setattr(settings_service, "org_today", lambda db: d)


def _mails():
    db = SessionLocal()
    rows = db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == KEY)).all()
    db.expunge_all()
    db.close()
    return rows


def _run_worker():
    db = SessionLocal()
    n = initiation.send_due(db)
    db.commit()
    db.close()
    return n


def _approved(admin, data, **kw):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def test_not_sent_before_the_window_then_sent_once(admin, data, monkeypatch):
    _today(monkeypatch, date(2027, 2, 1))
    b = _approved(admin, data)
    assert _mails() == [] and _run_worker() == 0
    detail = admin.get(f"/api/admin/bookings/{b['id']}").json()["booking"]["initiation_email"]
    assert detail["state"] == "scheduled" and detail["scheduled_for"] == "2027-02-22" and detail["days_before"] == 7
    _today(monkeypatch, date(2027, 2, 22))
    assert _run_worker() == 1
    assert {m.recipient for m in _mails()} == {"jane.poc@example.com"}
    assert _run_worker() == 0 and len(_mails()) == 1                      # only once
    assert admin.get(f"/api/admin/bookings/{b['id']}").json()["booking"]["initiation_email"]["state"] == "sent"


def test_approved_late_inside_window_goes_out_immediately(admin, req1, data, monkeypatch):
    _today(monkeypatch, date(2027, 2, 26))
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert _mails() == []                                                  # pending: nothing
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    m = _mails()
    assert len(m) == 1                                                     # ONE email: POC + requester in To, engineer in Cc
    assert set(m[0].recipient.split(", ")) == {"jane.poc@example.com", "req1@example.com"} or "jane.poc@example.com" in m[0].recipient


def test_pending_and_rejected_bookings_get_nothing(admin, req1, data, monkeypatch):
    _today(monkeypatch, date(2027, 2, 26))
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert _run_worker() == 0
    admin.post(f"/api/admin/bookings/{b['id']}/reject", json={"reason": "no"})
    assert _run_worker() == 0 and _mails() == []


def test_reschedule_sends_again_for_the_new_date(admin, data, monkeypatch):
    _today(monkeypatch, date(2027, 2, 26))
    b = _approved(admin, data)
    assert len(_mails()) == 1
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"poc_name": "Someone", "reason": "typo"}).status_code == 200
    assert len(_mails()) == 1                                              # details change: not re-sent
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"start_date": "2027-03-03", "reason": "moved"})
    assert r.status_code == 200, r.text
    assert len(_mails()) == 2
    assert "2027-03-03" in _mails()[-1].body or "2027-03-03" in _mails()[-1].subject


def test_global_setting_days_and_switch(admin, data, monkeypatch):
    assert admin.put("/api/admin/settings", json={"values": {"initiation_email_days_before": 3}}).status_code == 200
    _today(monkeypatch, date(2027, 2, 22))
    _approved(admin, data)
    assert _mails() == []                                                  # 7 days out, window is 3
    _today(monkeypatch, date(2027, 2, 26))
    assert _run_worker() == 1
    assert admin.put("/api/admin/settings", json={"values": {"initiation_email_days_before": -1}}).status_code == 422


def test_global_switch_off_stops_automatic_sending(admin, data, monkeypatch):
    admin.put("/api/admin/settings", json={"values": {"initiation_email_enabled": False}})
    _today(monkeypatch, date(2027, 2, 26))
    b = _approved(admin, data)
    assert _run_worker() == 0 and _mails() == []
    assert admin.get(f"/api/admin/bookings/{b['id']}").json()["booking"]["initiation_email"]["state"] == "disabled"
    # ...but the manual button still works
    assert admin.post(f"/api/admin/bookings/{b['id']}/send-initiation-email").status_code == 200
    assert len(_mails()) == 1


def test_per_activity_override_days_and_never(admin, data, monkeypatch):
    web, seg = data["acts"][0], data["acts"][1]
    assert admin.patch(f"/api/admin/activity-types/{web.id}", json={"initiation_days_before": 10}).status_code == 200
    assert admin.patch(f"/api/admin/activity-types/{seg.id}", json={"initiation_email_enabled": False}).status_code == 200
    _today(monkeypatch, date(2027, 2, 19))                                 # 10 days before MON
    _approved(admin, data, act_idx=0)
    _approved(admin, data, act_idx=1, resource_idx=1, application_name="Seg")
    assert len(_mails()) == 1 and _mails()[0].subject.endswith("(2027-03-01)")
    assert _run_worker() == 0


def test_manual_send_and_resend(admin, data, monkeypatch):
    _today(monkeypatch, date(2027, 2, 1))
    b = _approved(admin, data)
    r = admin.post(f"/api/admin/bookings/{b['id']}/send-initiation-email")
    assert r.status_code == 200 and r.json()["initiation_email"]["state"] == "sent"
    assert admin.post(f"/api/admin/bookings/{b['id']}/send-initiation-email").status_code == 200
    assert len(_mails()) == 2


def test_manual_send_requires_admin_and_approved(admin, req1, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert req1.post(f"/api/admin/bookings/{b['id']}/send-initiation-email").status_code == 403
    assert admin.post(f"/api/admin/bookings/{b['id']}/send-initiation-email").status_code == 409


def test_content_depends_on_activity_type():
    assert "Application URL" in initiation.default_details("Web Application PT")
    m = initiation.default_details("Mobile Application PT – Android and iOS")
    assert "APK" in m and "Application URL" not in m
    assert "OpenAPI" in initiation.default_details("API PT – 30 - 70 Endpoints")
    assert "code repository" in initiation.default_details("Hybrid Application PT – Single Codebase")
    both = initiation.default_details("Web Application PT with LLM")
    assert "Application URL" in both and "RAG" in both
    assert "IP whitelisting" in initiation.default_details("Something Unknown")


def test_custom_checklist_per_activity_type(admin, data, monkeypatch):
    web = data["acts"][0]
    r = admin.patch(f"/api/admin/activity-types/{web.id}", json={"initiation_details": "- Staging URL\n- A VPN token"})
    assert r.status_code == 200
    listed = [a for a in admin.get("/api/admin/activity-types").json() if a["id"] == str(web.id)][0]
    assert listed["initiation_details"].startswith("- Staging URL") and "Application URL" in listed["initiation_details_default"]
    _today(monkeypatch, date(2027, 2, 26))
    _approved(admin, data)
    assert "A VPN token" in _mails()[0].body and "Application URL" not in _mails()[0].body


def test_template_is_editable_and_requester_copy_follows_setting(admin, req1, data, monkeypatch):
    t = [x for x in admin.get("/api/admin/email-templates").json() if x["key"] == KEY]
    assert t, "template missing from Email & Templates"
    r = admin.put(f"/api/admin/email-templates/{KEY}", json={"subject_template": "Prep {{Application Name}}",
                                                              "body_template": "Need:\n{{Required Details}}", "is_active": True})
    assert r.status_code == 200, r.text
    admin.put("/api/admin/settings", json={"values": {"notify_requester_copy": False}})
    _today(monkeypatch, date(2027, 2, 26))
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    (m,) = _mails()
    assert m.subject == "Prep Customer Portal" and m.recipient == "jane.poc@example.com"


def test_assignee_is_cc_on_the_same_email(admin, data, monkeypatch):
    from app.services import email_sender
    _today(monkeypatch, date(2027, 2, 26))
    _approved(admin, data)
    (m,) = _mails()
    assert m.recipient == "jane.poc@example.com" and m.cc == "eng1@offsec.local"
    db = SessionLocal()
    try:
        row = db.get(EmailNotificationLog, m.id)
        msg = email_sender.build_message(db, row)
    finally:
        db.close()
    assert msg["To"] == "jane.poc@example.com" and msg["Cc"] == "eng1@offsec.local"


def test_cc_merges_settings_cc_without_duplicates(admin, data, monkeypatch):
    from app.services import email_sender
    admin.put("/api/admin/settings", json={"values": {"email_cc_recipients": ["boss@example.com", "ENG1@offsec.local", "jane.poc@example.com"]}})
    _today(monkeypatch, date(2027, 2, 26))
    _approved(admin, data)
    (m,) = _mails()
    db = SessionLocal()
    try:
        msg = email_sender.build_message(db, db.get(EmailNotificationLog, m.id))
    finally:
        db.close()
    assert msg["Cc"] == "eng1@offsec.local, boss@example.com"          # engineer once, POC (already in To) dropped


def test_no_engineer_email_means_no_cc(admin, data, monkeypatch):
    from app.models import SecurityResource
    db = SessionLocal()
    db.get(SecurityResource, data["resources"][0].id).engineer_email = None
    db.commit()
    db.close()
    _today(monkeypatch, date(2027, 2, 26))
    _approved(admin, data)
    (m,) = _mails()
    assert m.cc is None


def test_rich_details_with_a_table_reach_the_email(admin, data, monkeypatch):
    web = data["acts"][0]
    rich = ('<h3>Accounts</h3><table><thead><tr><th>Role</th><th>Count</th></tr></thead><tbody><tr><td>Admin</td><td>1</td></tr></tbody></table>'
            '<p onclick="x()">Share securely</p><script>bad()</script>')
    assert admin.patch(f"/api/admin/activity-types/{web.id}", json={"initiation_details": rich}).status_code == 200
    _today(monkeypatch, date(2027, 2, 26))
    _approved(admin, data)
    row = _mails()[0]
    assert "<table" in row.body_html and "<th " in row.body_html and "Application URL" not in row.body_html
    assert "onclick" not in row.body_html and "<script" not in row.body_html
    assert "Role | Count" in row.body and "Admin | 1" in row.body and "Share securely" in row.body and "<" not in row.body


def test_empty_rich_details_fall_back_to_the_built_in_checklist(admin, data, monkeypatch):
    web = data["acts"][0]
    assert admin.patch(f"/api/admin/activity-types/{web.id}", json={"initiation_details": "<p><br></p>"}).status_code == 200
    _today(monkeypatch, date(2027, 2, 26))
    _approved(admin, data)
    assert "Application URL" in _mails()[0].body
