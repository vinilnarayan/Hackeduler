"""Welcome email for new SSO users and confirmation email to the security engineer."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import EmailNotificationLog, SecurityResource

from .conftest import PASSWORD, booking_payload


def _mails(key):
    db = SessionLocal()
    rows = db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == key)).all()
    db.expunge_all()
    db.close()
    return rows


def test_sso_user_gets_welcome_email_with_app_url(admin):
    r = admin.post("/api/admin/users", json={"email": "new.person@test.local", "full_name": "New Person", "role": "requester"})
    assert r.status_code == 201
    (m,) = _mails("user_welcome")
    assert m.recipient == "new.person@test.local" and m.booking_id is None
    assert "New Person" in m.body and "http" in m.body and "single sign-on" in m.body.lower()


def test_password_user_gets_no_welcome_email_and_never_a_password(admin):
    admin.post("/api/admin/users", json={"email": "pw@test.local", "full_name": "Pw", "role": "requester", "password": PASSWORD})
    assert _mails("user_welcome") == []


def test_welcome_template_is_editable(admin):
    t = [x for x in admin.get("/api/admin/email-templates").json() if x["key"] == "user_welcome"][0]
    r = admin.put(f"/api/admin/email-templates/{t['key']}", json={"subject_template": "Welcome {{User Name}}", "body_template": "Go to {{App URL}}", "is_active": True})
    assert r.status_code == 200, r.text
    admin.post("/api/admin/users", json={"email": "e@test.local", "full_name": "Eve", "role": "requester"})
    assert _mails("user_welcome")[0].subject == "Welcome Eve"


def test_engineer_emailed_when_booking_approved(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert _mails("booking_confirmed_engineer") == []          # pending: nothing yet
    assert admin.post(f"/api/admin/bookings/{b['id']}/approve").status_code == 200
    (m,) = _mails("booking_confirmed_engineer")
    assert m.recipient == "eng1@offsec.local" and "Secret Engineer 1" in m.body and "Customer Portal" in m.body


def test_engineer_emailed_for_admin_created_booking(admin, data):
    assert admin.post("/api/admin/bookings", json=booking_payload(data, resource_idx=1)).status_code in (200, 201)
    assert [m.recipient for m in _mails("booking_confirmed_engineer")] == ["eng2@offsec.local"]


def test_engineer_without_email_is_skipped(admin, data):
    db = SessionLocal()
    db.get(SecurityResource, data["resources"][0].id).engineer_email = None
    db.commit()
    db.close()
    assert admin.post("/api/admin/bookings", json=booking_payload(data)).status_code in (200, 201)
    assert _mails("booking_confirmed_engineer") == []


def test_engineer_name_not_leaked_to_poc_email(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    assert all("Secret Engineer" not in m.body for m in _mails("booking_approved_poc"))
