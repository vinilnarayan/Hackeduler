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


def _to_addresses(key):
    """Every address in the To field of the emails of this template, and how many emails there were."""
    rows = _recipients(key)
    return {a.strip() for r in rows for a in r.split(",")}, len(rows)


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
    got, n = _to_addresses("booking_approved_poc")
    assert {"one@example.com", "two@example.com"} <= got
    assert n == 1                                                   # ONE email to all the POCs, not one each


def test_admin_booking_and_edit_with_several_pocs(admin, data):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, poc_email="a@example.com;b@example.com"))
    assert r.status_code == 201, r.text
    assert r.json()["poc_email"] == "a@example.com, b@example.com"
    got, n = _to_addresses("booking_approved_poc")
    assert {"a@example.com", "b@example.com"} <= got and n == 1
    e = admin.patch(f"/api/admin/bookings/{r.json()['id']}", json={"poc_email": "c@example.com, d@example.com", "reason": "x"})
    assert e.status_code == 200 and e.json()["poc_email"] == "c@example.com, d@example.com"
    got, n = _to_addresses("booking_modified_poc")
    assert {"a@example.com", "b@example.com"} <= got and n >= 1
    assert all(len(r.split(",")) >= 1 for r in _recipients("booking_modified_poc"))


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


def test_one_email_with_all_pocs_in_to_and_each_status_email(req1, admin, data):
    from app.services import email_sender
    r = req1.post("/api/bookings", json=booking_payload(data, poc_email="p1@example.com, p2@example.com, p3@example.com"))
    bid = r.json()["id"]
    admin.post(f"/api/admin/bookings/{bid}/approve")
    admin.patch(f"/api/admin/bookings/{bid}", json={"application_name": "Renamed App", "reason": "typo"})
    admin.post(f"/api/admin/bookings/{bid}/cancel", json={"reason": "no longer needed"})
    db = SessionLocal()
    try:
        for key in ("booking_approved_poc", "booking_modified_poc", "booking_cancelled_poc"):
            rows = db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == key)).all()
            assert len(rows) == 1, key
            msg = email_sender.build_message(db, rows[0])
            to = {a.strip() for a in msg["To"].split(",")}
            assert {"p1@example.com", "p2@example.com", "p3@example.com"} <= to, key
    finally:
        db.close()
