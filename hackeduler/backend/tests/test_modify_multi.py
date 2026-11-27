"""Modify a booking: add / remove / split additional resources, with the resource changes in the email."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, BookingResourceLock, EmailNotificationLog

from .conftest import booking_payload


def _locks(bid):
    db = SessionLocal()
    rows = db.scalars(select(BookingResourceLock).where(BookingResourceLock.booking_id == uuid.UUID(bid),
                                                        BookingResourceLock.lock_status.in_(("pending", "confirmed")))).all()
    db.expunge_all()
    db.close()
    return rows


def _mails(bid):
    db = SessionLocal()
    rows = list(db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.booking_id == uuid.UUID(bid),
                                                              EmailNotificationLog.template_key == "booking_modified_poc")))
    db.close()
    return rows


def _single(admin, data, **kw):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def _patch(admin, bid, **body):
    return admin.patch(f"/api/admin/bookings/{bid}", json={"reason": "scope change", **body})


def test_add_additional_resources_to_a_single_booking(admin, data):
    b = _single(admin, data)
    r = _patch(admin, b["id"], additional_resources=[{"resource_id": str(data["resources"][1].id)}])
    assert r.status_code == 200, r.text
    out = r.json()
    assert [x["id"] for x in out["extra_resources"]] == [str(data["resources"][1].id)]
    assert {l.resource_id for l in _locks(b["id"])} == {data["resources"][0].id, data["resources"][1].id}
    assert len(_locks(b["id"])) == 16 and out["duration_days"] == 8
    mail = _mails(b["id"])
    assert len(mail) == 1 and "Additional resources: None -> " in mail[0].body
    assert data["resources"][1].display_name in mail[0].body and "Secret Engineer 2" in mail[0].body
    db = SessionLocal()
    row = db.scalars(select(AuditLog).where(AuditLog.action == "booking.resources_changed")).one()
    db.close()
    assert row.new_value["additional_resource_ids"] == [str(data["resources"][1].id)]


def test_split_slice_extends_the_booking_and_is_listed_in_the_email(admin, data):
    b = _single(admin, data)
    r = _patch(admin, b["id"], additional_resources=[{"resource_id": str(data["resources"][1].id), "start_date": "2027-03-15", "working_days": 3}])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["end_date"] > b["end_date"] and out["duration_days"] == 8 + 3
    assert len([l for l in _locks(b["id"]) if l.resource_id == data["resources"][1].id]) == 3
    body = _mails(b["id"])[0].body
    assert "(3 working days)" in body and "End date:" in body


def test_remove_and_replace_resources_release_their_days(admin, data):
    b = _single(admin, data, additional_resource_ids=[str(data["resources"][1].id), str(data["resources"][2].id)]) \
        if False else admin.post("/api/admin/bookings", json=booking_payload(data, additional_resource_ids=[str(data["resources"][1].id), str(data["resources"][2].id)])).json()
    r = _patch(admin, b["id"], additional_resources=[{"resource_id": str(data["resources"][1].id)}])
    assert r.status_code == 200, r.text
    assert {l.resource_id for l in _locks(b["id"])} == {data["resources"][0].id, data["resources"][1].id}
    # the released engineer is told too (Cc) and resource 3 is bookable again
    mail = _mails(b["id"])[0]
    assert "eng3@offsec.local" in (mail.cc or "")
    assert admin.post("/api/admin/bookings", json=booking_payload(data, resource_idx=2, application_name="Other")).status_code == 201
    # releasing all of them makes it a single-resource booking again
    r = _patch(admin, b["id"], additional_resources=[])
    assert r.status_code == 200 and r.json()["extra_resources"] == []
    assert {l.resource_id for l in _locks(b["id"])} == {data["resources"][0].id}


def test_busy_resource_blocks_everything_and_changes_nothing(admin, data):
    b = _single(admin, data)
    _single(admin, data, resource_idx=1, application_name="Busy one")
    r = _patch(admin, b["id"], additional_resources=[{"resource_id": str(data["resources"][1].id)}])
    assert r.status_code == 409 and r.json()["error"]["code"] == "resource_unavailable"
    assert {l.resource_id for l in _locks(b["id"])} == {data["resources"][0].id} and not _mails(b["id"])


def test_rules(admin, data):
    b = _single(admin, data)
    r1 = str(data["resources"][1].id)
    assert _patch(admin, b["id"], additional_resources=[{"resource_id": str(data["resources"][0].id)}]).status_code == 422   # main resource
    assert _patch(admin, b["id"], additional_resources=[{"resource_id": r1}, {"resource_id": r1}]).status_code == 422          # twice
    assert _patch(admin, b["id"], additional_resources=[{"resource_id": r1}], force={"reason": "x", "acknowledged": True}).status_code == 422
    assert _patch(admin, b["id"], additional_resources=[]).status_code == 422                                                  # nothing to change


def test_main_dates_change_together_with_the_extras(admin, data):
    b = admin.post("/api/admin/bookings", json=booking_payload(data, additional_resource_ids=[str(data["resources"][1].id)])).json()
    extras = [{"resource_id": str(data["resources"][1].id)}]
    r = _patch(admin, b["id"], start_date="2027-03-15", additional_resources=extras)
    assert r.status_code == 200, r.text
    assert r.json()["start_date"] == "2027-03-15" and min(l.work_date for l in _locks(b["id"])).isoformat() == "2027-03-15"
    # dates alone on a multi-resource booking still needs the list
    r = _patch(admin, b["id"], start_date="2027-04-05")
    assert r.status_code == 409 and r.json()["error"]["code"] == "multi_resource_locked"


def test_booking_output_shows_each_extras_own_days(admin, data):
    b = _single(admin, data)
    r = _patch(admin, b["id"], additional_resources=[{"resource_id": str(data["resources"][1].id), "start_date": "2027-03-15", "working_days": 3}])
    x = r.json()["extra_resources"][0]
    assert x["start_date"] == "2027-03-15" and x["working_days"] == 3 and x["end_date"] == "2027-03-17"
