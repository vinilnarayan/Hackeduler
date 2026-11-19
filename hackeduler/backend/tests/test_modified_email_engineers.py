"""The 'Booking modified' email is ONE message: To the POCs, with the assigned engineer(s) in Cc - and the previous engineer
too when the resource was changed."""
from app.services import email_sender

from .conftest import MON, booking_payload


def _mk(admin, data, poc="poc@example.com"):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, 0, start=MON, duration_days=2, poc_email=poc))
    assert r.status_code == 201, r.text
    return r.json()


def _modified():
    return [m for m in email_sender.SENT_MESSAGES if "Booking Updated" in (m["Subject"] or "")]


def _drain():
    from app.db import SessionLocal
    db = SessionLocal()
    email_sender.process_outbox(db)
    db.close()


def test_reassigning_the_resource_copies_new_and_previous_engineer_on_one_email(admin, data):
    b = _mk(admin, data)                                          # resource 1 (eng1)
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"reason": "swap", "resource_id": str(data["resources"][1].id)})
    assert r.status_code == 200, r.text
    _drain()
    mails = _modified()
    assert len(mails) == 1                                        # one email, not one per person
    m = mails[0]
    assert m["To"] == "poc@example.com"
    cc = {a.strip() for a in m["Cc"].split(",")}
    assert {"eng2@offsec.local", "eng1@offsec.local"} <= cc       # new engineer and the one who lost the booking
    assert "Resource 02" in m.get_body(("plain",)).get_content()


def test_any_change_copies_the_assigned_engineer(admin, data):
    b = _mk(admin, data)
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"reason": "typo", "application_name": "Renamed"}).status_code == 200
    _drain()
    mails = _modified()
    assert len(mails) == 1 and mails[0]["Cc"] == "eng1@offsec.local"


def test_engineer_is_not_duplicated_when_also_a_poc(admin, data):
    assert admin.patch(f"/api/admin/resources/{data['resources'][0].id}", json={"engineer_email": "eng1@example.com"}).status_code == 200
    b = _mk(admin, data, poc="poc@example.com, eng1@example.com")
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"reason": "x", "application_name": "Renamed"}).status_code == 200
    _drain()
    m = _modified()[0]
    assert "eng1@example.com" in m["To"] and m["Cc"] is None
