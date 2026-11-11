"""Admin manual allocation: one confirmed booking that blocks several resources, with start/end dates."""
import uuid
from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.models import BookingResourceLock, EmailNotificationLog

from .conftest import booking_payload


def _locks(bid):
    db = SessionLocal()
    rows = db.scalars(select(BookingResourceLock).where(BookingResourceLock.booking_id == uuid.UUID(bid),
                                                        BookingResourceLock.lock_status.in_(("pending", "confirmed")))).all()
    db.expunge_all()
    db.close()
    return rows


def _multi(data, extras=(1, 2), **kw):
    return booking_payload(data, additional_resource_ids=[str(data["resources"][i].id) for i in extras], **kw)


def test_one_booking_blocks_all_selected_resources_and_is_confirmed(admin, data):
    r = admin.post("/api/admin/bookings", json=_multi(data))
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "approved"                               # no approval step
    assert len(b["extra_resources"]) == 2
    locks = _locks(b["id"])
    assert {l.resource_id for l in locks} == {x.id for x in data["resources"]}
    assert len(locks) == 3 * 8 and all(l.lock_status == "confirmed" for l in locks)


def test_selected_resources_are_busy_for_requesters_afterwards(admin, req1, data):
    admin.post("/api/admin/bookings", json=_multi(data, extras=(1,)))
    r = req1.post("/api/bookings", json=booking_payload(data, resource_idx=1, application_name="Other"))
    assert r.status_code == 409
    assert req1.post("/api/bookings", json=booking_payload(data, resource_idx=2, application_name="Other")).status_code == 201


def test_all_or_nothing_when_one_resource_is_busy(admin, req1, data):
    assert req1.post("/api/bookings", json=booking_payload(data, resource_idx=2, application_name="Busy")).status_code == 201
    r = admin.post("/api/admin/bookings", json=_multi(data))
    assert r.status_code == 409 and r.json()["error"]["code"] == "resource_unavailable"
    assert "Resource 03" in r.json()["error"]["message"]
    # nothing was created or blocked for the free resources
    assert req1.post("/api/bookings", json=booking_payload(data, resource_idx=1, application_name="Free")).status_code == 201


def test_end_date_can_be_set_on_a_multi_resource_booking(admin, data):
    r = admin.post("/api/admin/bookings", json=_multi(data, end_date="2027-03-05"))
    assert r.status_code == 201, r.text
    assert r.json()["start_date"] == "2027-03-01" and r.json()["end_date"] == "2027-03-05"


def test_invalid_selections(admin, data):
    rid = str(data["resources"][0].id)
    assert admin.post("/api/admin/bookings", json=booking_payload(data, additional_resource_ids=[rid])).status_code == 422
    other = str(data["resources"][1].id)
    assert admin.post("/api/admin/bookings", json=booking_payload(data, additional_resource_ids=[other, other])).status_code == 422
    p = booking_payload(data, additional_resource_ids=[other])
    p.pop("resource_id")
    assert admin.post("/api/admin/bookings", json=p).status_code == 422
    force = {"confirm": True, "reason": "x"}
    assert admin.post("/api/admin/bookings", json={**booking_payload(data, additional_resource_ids=[other]), "force": force}).status_code == 422


def test_requesters_cannot_use_additional_resources(req1, data):
    assert req1.post("/api/bookings", json=booking_payload(data, additional_resource_ids=[str(data["resources"][1].id)])).status_code == 422


def test_admin_booking_is_always_confirmed(admin, data):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, initial_status="pending_approval"))
    assert r.status_code == 201 and r.json()["status"] == "approved"


def test_cancel_releases_every_resource(admin, data):
    b = admin.post("/api/admin/bookings", json=_multi(data)).json()
    assert admin.post(f"/api/admin/bookings/{b['id']}/cancel", json={"reason": "no longer needed"}).status_code == 200
    assert _locks(b["id"]) == []
    assert admin.post("/api/admin/bookings", json=_multi(data, application_name="Again")).status_code == 201


def test_schedule_edit_blocked_but_details_editable(admin, data):
    b = admin.post("/api/admin/bookings", json=_multi(data)).json()
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"start_date": "2027-03-08", "reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "multi_resource_locked"
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"poc_name": "New POC", "reason": "typo"}).status_code == 200


def test_every_engineer_is_emailed(admin, data):
    admin.post("/api/admin/bookings", json=_multi(data))
    db = SessionLocal()
    rec = sorted(m.recipient for m in db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.template_key == "booking_confirmed_engineer")))
    db.close()
    assert rec == ["eng1@offsec.local", "eng2@offsec.local", "eng3@offsec.local"]


def test_resource_with_extra_booking_cannot_be_deleted(admin, data):
    admin.post("/api/admin/bookings", json=_multi(data))
    r = admin.delete(f"/api/admin/resources/{data['resources'][2].id}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "resource_in_use"
    assert admin.get(f"/api/admin/resources/{data['resources'][2].id}/allocation").json()["bookings"]
