"""The assigned engineer edits the details of their own approved booking; the 'Booking Updated' email names them."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, Booking, EmailNotificationLog, EmailTemplate

from .conftest import MON, PASSWORD, Api, booking_payload


def _setup(admin, data, resource_idx=0, **kw):
    b = admin.post("/api/admin/bookings", json=booking_payload(data, resource_idx=resource_idx, start=MON, **kw)).json()
    # the booking belongs to the admin account here; give it a real requester so the copy can be checked
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
                                                              EmailNotificationLog.template_key == "booking_modified_poc")))
    db.close()
    return rows


def test_engineer_edits_details_and_everyone_is_emailed_with_their_name(admin, data):
    b, eng = _setup(admin, data)
    r = eng.patch(f"/api/resource/bookings/{b['id']}", json={"poc_name": "New POC", "poc_email": "new@poc.example",
                                                             "pci_dss_scope": False, "reason": "POC changed"})
    assert r.status_code == 200, r.text
    assert r.json()["poc_name"] == "New POC" and r.json()["poc_email"] == "new@poc.example"
    mails = _mails(b["id"])
    assert len(mails) == 2                                    # the POCs, plus the address that was removed (existing behaviour)
    mail = next(m for m in mails if "new@poc.example" in m.recipient)
    assert all("updated by Eng One." in m.body for m in mails)
    assert "req1@test.local" in mail.recipient and "eng1@offsec.local" in (mail.cc or "")      # requester (setting on) + engineer
    assert "POC changed" in mail.body and "POC name:" in mail.body
    db = SessionLocal()
    row = db.scalars(select(AuditLog).where(AuditLog.action == "booking.modified")).one()
    db.close()
    assert row.actor_email == "eng1@test.local" and row.actor_role == "resource" and row.reason == "POC changed"


def test_admin_edit_email_names_the_admin_and_copies_the_requester(admin, data):
    b, _ = _setup(admin, data)
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"poc_name": "Someone", "reason": "typo"}).status_code == 200
    (mail,) = _mails(b["id"])
    assert f"updated by {data['users']['admin'].full_name}." in mail.body
    assert "req1@test.local" in mail.recipient


def test_requester_still_gets_a_copy_when_the_requester_copy_setting_is_off(admin, data):
    assert admin.put("/api/admin/settings", json={"values": {"notify_requester_copy": False}}).status_code == 200
    b, eng = _setup(admin, data)
    assert eng.patch(f"/api/resource/bookings/{b['id']}", json={"poc_name": "Someone", "reason": "typo"}).status_code == 200
    (mail,) = _mails(b["id"])
    assert "req1@test.local" not in mail.recipient and "req1@test.local" in (mail.cc or "")


def test_reason_is_required_and_only_details_are_accepted(admin, data):
    b, eng = _setup(admin, data)
    url = f"/api/resource/bookings/{b['id']}"
    assert eng.patch(url, json={"poc_name": "X"}).status_code == 422                                     # no reason
    assert eng.patch(url, json={"poc_name": "X", "reason": " "}).status_code in (400, 422)
    for bad in ({"start_date": "2027-04-05"}, {"end_date": "2027-04-09"}, {"resource_id": str(uuid.uuid4())},
                {"activity_type_id": str(uuid.uuid4())}, {"product_id": str(uuid.uuid4())}, {"implementation_id": str(uuid.uuid4())}):
        assert eng.patch(url, json={**bad, "reason": "x"}).status_code == 422                            # strict schema
    assert eng.patch(url, json={"poc_email": "not-an-email", "reason": "x"}).status_code == 422
    assert eng.patch(url, json={"reason": "nothing changed"}).status_code == 422                          # no changes
    assert not _mails(b["id"])


def test_only_the_assigned_engineer_on_an_approved_booking(admin, req1, data):
    b, eng = _setup(admin, data)
    other = admin.post("/api/admin/bookings", json=booking_payload(data, resource_idx=1, application_name="Other")).json()
    assert eng.patch(f"/api/resource/bookings/{other['id']}", json={"poc_name": "X", "reason": "x"}).status_code == 404
    assert req1.patch(f"/api/resource/bookings/{b['id']}", json={"poc_name": "X", "reason": "x"}).status_code == 403
    assert admin.patch(f"/api/resource/bookings/{b['id']}", json={"poc_name": "X", "reason": "x"}).status_code == 403
    assert admin.post(f"/api/admin/bookings/{b['id']}/cancel", json={"reason": "gone"}).status_code == 200
    assert eng.patch(f"/api/resource/bookings/{b['id']}", json={"poc_name": "X", "reason": "x"}).status_code == 404


def test_additional_resource_engineer_can_edit_too(admin, data):
    b = admin.post("/api/admin/bookings", json=booking_payload(data, additional_resource_ids=[str(data["resources"][1].id)])).json()
    admin.post("/api/admin/users", json={"email": "eng2@test.local", "full_name": "Eng Two", "password": PASSWORD,
                                         "role": "resource", "resource_id": str(data["resources"][1].id)})
    r = Api("eng2@test.local").patch(f"/api/resource/bookings/{b['id']}", json={"additional_comments": "hello", "reason": "note"})
    assert r.status_code == 200 and r.json()["additional_comments"] == "hello"
    assert "updated by Eng Two." in _mails(b["id"])[0].body


def test_template_wording_and_variable():
    from app.services.notifications import ALLOWED_VARIABLES, DEFAULT_TEMPLATES
    assert "Modified By" in ALLOWED_VARIABLES
    assert "has been updated by {{Modified By}}." in DEFAULT_TEMPLATES["booking_modified_poc"]["body"]


def test_migration_updates_only_the_original_sentence():
    import importlib.util
    from pathlib import Path

    from sqlalchemy import text

    spec = importlib.util.spec_from_file_location("m0024", Path(__file__).parent.parent / "alembic/versions/0024_modified_by_email_wording.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sql = ("UPDATE email_templates SET body_template = replace(body_template, '%s', '%s') "
           "WHERE key = 'booking_modified_poc' AND position('%s' in body_template) > 0" % (m.OLD, m.NEW, m.OLD))
    db = SessionLocal()
    try:
        db.add(EmailTemplate(id=uuid.uuid4(), key="booking_modified_poc", name="x", subject_template="s",
                             body_template=f"Hello,\n\n{m.OLD}\n\nBye"))
        db.flush()
        db.execute(text(sql)); db.execute(text(sql))                                   # idempotent
        row = db.scalars(select(EmailTemplate).where(EmailTemplate.key == "booking_modified_poc")).one()
        assert row.body_template == f"Hello,\n\n{m.NEW}\n\nBye"
        row.body_template = "A custom template without the sentence"
        db.flush()
        db.execute(text(sql))
        assert row.body_template == "A custom template without the sentence"
    finally:
        db.rollback()
        db.close()
