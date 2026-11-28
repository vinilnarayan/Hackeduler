"""An administrator can edit a booking in any status: completed bookings fully, rejected/cancelled/expired ones their details."""
import uuid

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Booking, BookingResourceLock, EmailNotificationLog

from .conftest import MON, booking_payload


def _make(admin, data, status):
    b = admin.post("/api/admin/bookings", json=booking_payload(data, start=MON)).json()
    db = SessionLocal()
    bk = db.get(Booking, uuid.UUID(b["id"]))
    bk.status = status
    db.commit()
    db.close()
    return b


def _patch(admin, bid, **body):
    return admin.patch(f"/api/admin/bookings/{bid}", json={"reason": "correction", **body})


def _mails(bid):
    db = SessionLocal()
    rows = list(db.scalars(select(EmailNotificationLog).where(EmailNotificationLog.booking_id == uuid.UUID(bid))))
    db.close()
    return rows


def test_completed_booking_details_and_schedule_can_be_edited(admin, data):
    b = _make(admin, data, "completed")
    r = _patch(admin, b["id"], application_name="Renamed App", poc_name="New Poc")
    assert r.status_code == 200, r.text
    assert r.json()["application_name"] == "Renamed App" and r.json()["status"] == "completed"
    r = _patch(admin, b["id"], additional_resources=[{"resource_id": str(data["resources"][1].id)}])
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()["extra_resources"]] == [str(data["resources"][1].id)]
    db = SessionLocal()
    locks = db.scalars(select(BookingResourceLock).where(BookingResourceLock.booking_id == uuid.UUID(b["id"]),
                                                         BookingResourceLock.lock_status.in_(("pending", "confirmed")))).all()
    db.close()
    assert locks and {l.lock_status for l in locks} == {"confirmed"}
    sent = [m for m in _mails(b["id"]) if m.template_key == "booking_modified_poc"]
    assert len(sent) == 2 and "Renamed App" in sent[0].body + sent[1].body   # a correction is emailed like any other edit


@pytest.mark.parametrize("status", ["rejected", "cancelled", "expired"])
def test_inactive_booking_details_editable_schedule_is_not(admin, data, status):
    b = _make(admin, data, status)
    r = _patch(admin, b["id"], application_version="9.9", poc_email="fixed@poc.example")
    assert r.status_code == 200, r.text
    assert r.json()["application_version"] == "9.9" and r.json()["status"] == status
    assert [m for m in _mails(b["id"]) if m.template_key == "booking_modified_poc"] == []                              # nothing is emailed for a booking that holds no reservation
    r = _patch(admin, b["id"], start_date="2027-03-22")
    assert r.status_code == 409
    assert _patch(admin, b["id"], additional_resources=[{"resource_id": str(data["resources"][1].id)}]).status_code == 409


def test_engineer_still_limited_to_approved(admin, data):
    from .conftest import PASSWORD, Api
    b = _make(admin, data, "completed")
    admin.post("/api/admin/users", json={"email": "eng1@test.local", "full_name": "Eng One", "password": PASSWORD,
                                         "role": "resource", "resource_id": str(data["resources"][0].id)})
    r = Api("eng1@test.local").patch(f"/api/resource/bookings/{b['id']}", json={"poc_name": "X", "reason": "r"})
    assert r.status_code in (404, 409)
