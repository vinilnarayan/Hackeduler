"""Booking workflow acceptance tests (criteria 2-15, 23-28)."""
import uuid
from datetime import date, timedelta

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import AuditLog, Booking, BookingResourceLock, EmailNotificationLog

from .conftest import MON, booking_payload


def _emails(template=None, booking_id=None):
    db = SessionLocal()
    q = select(EmailNotificationLog)
    if template:
        q = q.where(EmailNotificationLog.template_key == template)
    if booking_id:
        q = q.where(EmailNotificationLog.booking_id == uuid.UUID(booking_id))
    rows = db.scalars(q).all()
    db.close()
    return rows


def _active_locks(booking_id):
    db = SessionLocal()
    rows = db.scalars(select(BookingResourceLock.work_date).where(
        BookingResourceLock.booking_id == uuid.UUID(booking_id), BookingResourceLock.lock_status.in_(("pending", "confirmed")))
        .order_by(BookingResourceLock.work_date)).all()
    db.close()
    return rows


# ---------------------------------------------------------------- calculation
def test_availability_preview_calculates_end_date_with_holiday(req1, admin, data):
    admin.post("/api/admin/holidays", json={"name": "Holi", "holiday_date": "2027-03-03"})
    r = req1.post("/api/availability/check", json={"resource_id": str(data["resources"][0].id),
                                                   "activity_type_id": str(data["acts"][0].id), "start_date": "2027-03-01"})
    body = r.json()
    assert body["available"] is True
    assert body["duration_days"] == 8
    assert body["end_date"] == "2027-03-11"
    assert "2027-03-03" not in body["work_dates"] and "2027-03-06" not in body["work_dates"]


def test_leave_only_affects_its_resource(req1, admin, data):
    r0, r1 = data["resources"][0], data["resources"][1]
    assert admin.post("/api/admin/leaves", json={"resource_id": str(r0.id), "start_date": "2027-03-08",
                                                 "end_date": "2027-03-09", "leave_type": "Annual"}).status_code == 201
    a = req1.post("/api/availability/check", json={"resource_id": str(r0.id), "activity_type_id": str(data["acts"][0].id),
                                                   "start_date": "2027-03-01"}).json()
    b = req1.post("/api/availability/check", json={"resource_id": str(r1.id), "activity_type_id": str(data["acts"][0].id),
                                                   "start_date": "2027-03-01"}).json()
    assert a["end_date"] == "2027-03-12" and b["end_date"] == "2027-03-10"
    cal = req1.get("/api/calendar?start=2027-03-08&end=2027-03-08").json()
    assert cal["resources"][0]["days"][0] == {"date": "2027-03-08", "state": "non_working", "reason": "leave"}
    assert cal["resources"][1]["days"][0]["state"] == "available"
    assert "Annual" not in str(cal)  # leave type/reason not disclosed


def test_cannot_start_on_non_working_day(req1, admin, data):
    r = req1.post("/api/bookings", json=booking_payload(data, start=date(2027, 3, 6)))
    assert r.status_code == 409 and "weekend" in r.json()["error"]["message"]
    admin.post("/api/admin/holidays", json={"name": "Holi", "holiday_date": "2027-03-03"})
    r = req1.post("/api/bookings", json=booking_payload(data, start=date(2027, 3, 3)))
    assert r.status_code == 409 and "holiday" in r.json()["error"]["message"]
    pre = req1.post("/api/availability/check", json={"resource_id": str(data["resources"][0].id),
                                                     "activity_type_id": str(data["acts"][0].id), "start_date": "2027-03-06"}).json()
    assert pre["available"] is False and pre["reason"] == "non_working_start"
    assert pre["suggested_start_date"] == "2027-03-08"


def test_additional_duration_rule(req1, data):
    ok = req1.post("/api/availability/check", json={"resource_id": str(data["resources"][0].id),
                                                    "activity_type_id": str(data["acts"][2].id), "start_date": "2027-03-01",
                                                    "additional_days": 2}).json()
    assert ok["duration_days"] == 6 and ok["end_date"] == "2027-03-08"
    bad = req1.post("/api/availability/check", json={"resource_id": str(data["resources"][0].id),
                                                     "activity_type_id": str(data["acts"][2].id), "start_date": "2027-03-01",
                                                     "additional_days": 3})
    assert bad.status_code == 422


# ---------------------------------------------------------------- submission
def test_submission_creates_uuid4_pending_booking_with_snapshot(req1, data):
    r = req1.post("/api/bookings", json=booking_payload(data))
    assert r.status_code == 201
    b = r.json()
    assert uuid.UUID(b["id"]).version == 4
    assert b["status"] == "pending_approval" and b["status_label"] == "Pending Approval"
    assert b["end_date"] == "2027-03-10" and b["duration_days"] == 8
    assert len(_active_locks(b["id"])) == 8
    assert len(_emails("booking_submitted_admin", b["id"])) == 1


def test_requester_cannot_supply_backend_fields(req1, data):
    for extra in ({"end_date": "2027-03-02"}, {"duration_days": 1}, {"status": "approved"},
                  {"force": {"confirm": True, "reason": "x"}}):
        r = req1.post("/api/bookings", json={**booking_payload(data), **extra})
        assert r.status_code == 422, extra


def test_past_start_date_rejected(req1, data):
    r = req1.post("/api/bookings", json=booking_payload(data, start=date.today() - timedelta(days=7)))
    assert r.status_code == 422


def test_pending_and_approved_block_overlaps(req1, req2, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    r = req2.post("/api/bookings", json=booking_payload(data, start=date(2027, 3, 9)))
    assert r.status_code == 409
    assert r.json()["error"]["message"].startswith("The selected resource is no longer available")
    assert "booking_ids" not in str(r.json())  # requester never sees other booking ids
    pre = req2.post("/api/availability/check", json={"resource_id": str(data["resources"][0].id),
                                                     "activity_type_id": str(data["acts"][0].id), "start_date": "2027-03-09"}).json()
    assert pre["available"] is False and pre["suggested_start_date"] == "2027-03-11"
    assert {x["display_name"] for x in pre["alternative_resources"]} == {"Resource 02", "Resource 03"}
    # approved also blocks
    assert admin.post(f"/api/admin/bookings/{b['id']}/approve").status_code == 200
    assert req2.post("/api/bookings", json=booking_payload(data, start=date(2027, 3, 2))).status_code == 409
    # different resource fine; adjacent dates fine
    assert req2.post("/api/bookings", json=booking_payload(data, resource_idx=1)).status_code == 201
    assert req2.post("/api/bookings", json=booking_payload(data, start=date(2027, 3, 11))).status_code == 201


def test_calendar_colour_states(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    req1.post("/api/bookings", json=booking_payload(data, resource_idx=1))
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    admin.patch(f"/api/admin/resources/{data['resources'][2].id}", json={"is_active": False})
    cal = req1.get(f"/api/calendar?start=2027-03-01&end=2027-03-07&activity_type_id={data['acts'][0].id}").json()
    r0, r1, r2 = (x["days"] for x in cal["resources"])
    assert r0[0]["state"] == "occupied"      # red
    assert r1[0]["state"] == "reserved"      # blue
    assert r2[0]["state"] == "inactive"      # grey
    assert r0[5]["state"] == "non_working" and r0[5]["reason"] == "weekend"
    cal2 = req1.get(f"/api/calendar?start=2027-03-11&end=2027-03-12&activity_type_id={data['acts'][0].id}").json()
    assert cal2["resources"][0]["days"][0]["state"] == "available"   # green
    # Resource 02 has a pending booking Mar 1-10: an 8-day booking can't start on Feb 26 -> limited (yellow)
    cal3 = req1.get(f"/api/calendar?start=2027-02-26&end=2027-02-26&activity_type_id={data['acts'][0].id}").json()
    assert cal3["resources"][1]["days"][0]["state"] == "limited"


# ---------------------------------------------------------------- approval / rejection
def test_approval_notifies_poc_and_confirms_locks(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    r = admin.post(f"/api/admin/bookings/{b['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    db = SessionLocal()
    st = set(db.scalars(select(BookingResourceLock.lock_status).where(BookingResourceLock.booking_id == uuid.UUID(b["id"]))))
    bk = db.get(Booking, uuid.UUID(b["id"]))
    assert st == {"confirmed"} and bk.approved_by is not None and bk.approved_at is not None
    db.close()
    recips = {e.recipient for e in _emails("booking_approved_poc", b["id"])}
    assert "jane.poc@example.com" in recips
    assert admin.post(f"/api/admin/bookings/{b['id']}/approve").status_code == 409  # already approved


def test_approval_revalidates_after_holiday_added(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    h = admin.post("/api/admin/holidays", json={"name": "Surprise Holiday", "holiday_date": "2027-03-04"}).json()
    assert h["flagged_bookings"] == [b["id"]]
    r = admin.post(f"/api/admin/bookings/{b['id']}/approve")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "override_required"
    assert any(i["type"] == "schedule_changed" for i in err["details"]["issues"])
    # booking was NOT silently moved
    assert req1.get(f"/api/bookings/{b['id']}").json()["end_date"] == "2027-03-10"
    # admin recalculates and then approves
    m = admin.patch(f"/api/admin/bookings/{b['id']}", json={"recalculate": True, "reason": "Holiday added"})
    assert m.status_code == 200 and m.json()["end_date"] == "2027-03-11"
    assert admin.post(f"/api/admin/bookings/{b['id']}/approve").status_code == 200


def test_rejection_requires_reason_releases_and_notifies(req1, req2, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert admin.post(f"/api/admin/bookings/{b['id']}/reject", json={"reason": "   "}).status_code == 422
    assert admin.post(f"/api/admin/bookings/{b['id']}/reject", json={}).status_code == 422
    r = admin.post(f"/api/admin/bookings/{b['id']}/reject", json={"reason": "Scope unclear"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert _active_locks(b["id"]) == []
    mails = _emails("booking_rejected_poc", b["id"])
    assert mails and "Scope unclear" in mails[0].body
    assert req2.post("/api/bookings", json=booking_payload(data)).status_code == 201  # slot released


def test_cancellation_releases(req1, req2, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert req1.post(f"/api/bookings/{b['id']}/cancel", json={"reason": "No longer needed"}).status_code == 200
    assert _active_locks(b["id"]) == []
    assert req2.post("/api/bookings", json=booking_payload(data)).status_code == 201


def test_requester_cannot_directly_cancel_approved(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    assert req1.post(f"/api/bookings/{b['id']}/cancel", json={"reason": "x"}).status_code == 403
    cr = req1.post(f"/api/bookings/{b['id']}/change-requests", json={"request_type": "cancel", "reason": "Release delayed"})
    assert cr.status_code == 201 and cr.json()["mode"] == "requested"
    assert _emails("change_request_admin", b["id"])
    crs = admin.get("/api/admin/change-requests").json()
    r = admin.post(f"/api/admin/change-requests/{crs[0]['id']}/decide", json={"approve": True})
    assert r.status_code == 200
    assert req1.get(f"/api/bookings/{b['id']}").json()["status"] == "cancelled"
    assert _emails("booking_cancelled_poc", b["id"])


def test_reschedule_request_flow(req1, req2, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    r = req1.post(f"/api/bookings/{b['id']}/change-requests",
                  json={"request_type": "reschedule", "reason": "Build slipped", "proposed_start_date": "2027-03-15"})
    assert r.status_code == 201 and r.json()["preview"]["available"] is True
    assert r.json()["preview"]["end_date"] == "2027-03-24"
    # duplicate pending request blocked
    assert req1.post(f"/api/bookings/{b['id']}/change-requests",
                     json={"request_type": "cancel", "reason": "x"}).status_code == 409
    cr_id = r.json()["change_request_id"]
    assert admin.post(f"/api/admin/change-requests/{cr_id}/decide", json={"approve": True}).status_code == 200
    got = req1.get(f"/api/bookings/{b['id']}").json()
    assert got["start_date"] == "2027-03-15" and got["end_date"] == "2027-03-24" and got["status"] == "approved"
    assert _active_locks(b["id"])[0] == date(2027, 3, 15)
    assert req2.post("/api/bookings", json=booking_payload(data)).status_code == 201  # old slot released
    assert _emails("booking_modified_poc", b["id"])


def test_reschedule_conflict_keeps_old_reservation(req1, req2, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    other = req2.post("/api/bookings", json=booking_payload(data, start=date(2027, 3, 15))).json()
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"start_date": "2027-03-12", "reason": "move"})
    assert r.status_code == 409
    assert _active_locks(b["id"])[0] == MON  # original allocation intact
    assert len(_active_locks(other["id"])) == 8


def test_pending_expiry_releases(req1, req2, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    db = SessionLocal()
    db.execute(update(Booking).where(Booking.id == uuid.UUID(b["id"])).values(expires_at="2020-01-01T00:00:00Z"))
    db.execute(update(BookingResourceLock).where(BookingResourceLock.booking_id == uuid.UUID(b["id"]))
               .values(expires_at="2020-01-01T00:00:00Z"))
    db.commit()
    db.close()
    # an expired-but-not-yet-swept reservation no longer blocks, and is swept within the booking txn
    assert req2.post("/api/bookings", json=booking_payload(data)).status_code == 201
    assert req1.get(f"/api/bookings/{b['id']}").json()["status"] == "expired"
    assert _active_locks(b["id"]) == []
    assert _emails("booking_expired_requester", b["id"])


def test_worker_expires(req1, data):
    from app.worker import run_once

    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    db = SessionLocal()
    db.execute(update(Booking).where(Booking.id == uuid.UUID(b["id"])).values(expires_at="2020-01-01T00:00:00Z"))
    db.commit()
    db.close()
    r = run_once()
    assert r["expired"] == 1
    assert req1.get(f"/api/bookings/{b['id']}").json()["status"] == "expired"


# ---------------------------------------------------------------- configuration and history
def test_activity_duration_change_does_not_alter_existing_booking(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    act = data["acts"][0]
    assert admin.patch(f"/api/admin/activity-types/{act.id}", json={"base_duration_days": 10}).status_code == 200
    assert admin.patch(f"/api/admin/activity-types/{act.id}", json={"base_duration_days": 0}).status_code == 422
    assert admin.patch(f"/api/admin/activity-types/{act.id}", json={"base_duration_days": 2.5}).status_code == 422
    got = req1.get(f"/api/bookings/{b['id']}").json()
    assert got["duration_days"] == 8 and got["end_date"] == "2027-03-10"
    assert len(_active_locks(b["id"])) == 8


def test_deactivation_preserves_history_and_blocks_new_bookings(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    act = data["acts"][0]
    res = data["resources"][0]
    assert admin.patch(f"/api/admin/activity-types/{act.id}", json={"is_active": False}).status_code == 200
    r = admin.patch(f"/api/admin/resources/{res.id}", json={"is_active": False, "reason": "Engineer left"})
    assert r.status_code == 200
    got = req1.get(f"/api/bookings/{b['id']}").json()
    assert got["status"] == "approved" and got["activity_name"] == "Web Application PT"
    assert admin.get(f"/api/admin/bookings/{b['id']}").status_code == 200
    assert act.id not in [a["id"] for a in req1.get("/api/activity-types").json()]
    assert req1.post("/api/bookings", json=booking_payload(data, act_idx=0, resource_idx=1)).status_code == 422
    assert req1.post("/api/bookings", json=booking_payload(data, act_idx=1, start=date(2027, 4, 5))).status_code == 409
    conf = admin.get("/api/admin/conflicts").json()
    assert any(c["conflict_type"] == "inactive_resource" and c["booking_id"] == b["id"] for c in conf)


def test_leave_after_approval_flags_for_review(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    r = admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][0].id), "start_date": "2027-03-03",
                                              "end_date": "2027-03-03", "leave_type": "Sick"})
    assert r.json()["flagged_bookings"] == [b["id"]]
    got = admin.get(f"/api/admin/bookings/{b['id']}").json()
    assert got["booking"]["needs_review"] is True
    assert got["booking"]["start_date"] == "2027-03-01" and got["booking"]["end_date"] == "2027-03-10"  # not moved
    assert len(_active_locks(b["id"])) == 8
    confs = admin.get("/api/admin/conflicts?status=open").json()
    assert confs[0]["conflict_type"] == "leave"
    assert _emails("booking_impacted_poc", b["id"])
    # resolution workflow
    assert admin.post(f"/api/admin/conflicts/{confs[0]['id']}/resolve", json={"resolution_note": ""}).status_code == 422
    rr = admin.post(f"/api/admin/conflicts/{confs[0]['id']}/resolve", json={"resolution_note": "Backup engineer covers 3 Mar"})
    assert rr.status_code == 200 and rr.json()["status"] == "resolved"
    assert admin.get(f"/api/admin/bookings/{b['id']}").json()["booking"]["needs_review"] is False
    assert admin.get("/api/admin/conflicts?status=resolved").json()[0]["resolution_note"].startswith("Backup")


def test_holiday_delete_flags_spanning_booking(req1, admin, data):
    h = admin.post("/api/admin/holidays", json={"name": "H", "holiday_date": "2027-03-03"}).json()["holiday"]
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert b["end_date"] == "2027-03-11"
    r = admin.delete(f"/api/admin/holidays/{h['id']}")
    assert r.json()["flagged_bookings"] == [b["id"]]


def test_admin_modification_preserves_previous_values_in_audit(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"resource_id": str(data["resources"][1].id),
                                                            "application_version": "2.0", "reason": "Rebalance"})
    assert r.status_code == 200 and r.json()["resource_display_name"] == "Resource 02"
    d = admin.get(f"/api/admin/bookings/{b['id']}").json()
    actions = [a["action"] for a in d["audit"]]
    assert "booking.reassigned" in actions and "booking.details_changed" in actions and "booking.modified" in actions
    mod = next(a for a in d["audit"] if a["action"] == "booking.modified")
    assert mod["previous_value"]["application_version"] == "1.0"
    assert mod["previous_value"]["resource_id"] == str(data["resources"][0].id)
    assert mod["new_value"]["application_version"] == "2.0"
    assert mod["reason"] == "Rebalance"
    mail = _emails("booking_modified_poc", b["id"])
    assert mail and "Resource 01 -> Resource 02" in mail[0].body
    assert admin.patch(f"/api/admin/bookings/{b['id']}", json={"application_version": "3"}).status_code == 422  # reason required


def test_admin_direct_create(admin, data):
    p = booking_payload(data, poc_email="poc@example.com")
    r = admin.post("/api/admin/bookings", json={**p, "initial_status": "approved", "reason": "Urgent audit"})
    assert r.status_code == 201 and r.json()["status"] == "approved" and r.json()["source"] == "admin"
    assert _emails("booking_approved_poc", r.json()["id"])
    db = SessionLocal()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "booking.admin_created")) is not None
    db.close()


def test_admin_explicit_end_date_and_duration_override(admin, data):
    p = booking_payload(data)
    r = admin.post("/api/admin/bookings", json={**p, "end_date": "2027-03-05"})
    assert r.status_code == 201 and r.json()["duration_days"] == 5 and r.json()["end_date"] == "2027-03-05"
    r2 = admin.post("/api/admin/bookings", json={**booking_payload(data, resource_idx=1), "duration_days": 3})
    assert r2.json()["end_date"] == "2027-03-03"


def test_exports(admin, req1, data):
    req1.post("/api/bookings", json=booking_payload(data, application_name="=HYPERLINK(\"http://x\")"))
    csv_r = admin.get("/api/admin/reports/bookings.csv")
    assert csv_r.status_code == 200 and "'=HYPERLINK" in csv_r.text
    x = admin.get("/api/admin/reports/bookings.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_dashboards(admin, req1, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    d = admin.get("/api/admin/dashboard?start=2027-03-01&end=2027-03-31").json()
    assert d["kpis"]["active_resources"] == 3 and d["kpis"]["approved"] == 1
    mar = next(m for m in d["charts"]["monthly_utilization"] if m["month"] == "2027-03")
    assert mar["used_days"] == 8 and mar["capacity_days"] == 3 * 23
    me = req1.get("/api/me/dashboard").json()
    assert me["counts"]["approved"] == 1 and len(me["upcoming"]) == 1


def test_holiday_import_csv(admin):
    content = "name,date,description\nNew Year,2027-01-01,\nBad,notadate,\nPongal,15/01/2027,Harvest\n"
    r = admin.c.post("/api/admin/holidays/import", files={"file": ("h.csv", content, "text/csv")},
                     headers={"X-CSRF-Token": admin.csrf})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2 and len(r.json()["errors"]) == 1
    names = [h["name"] for h in admin.get("/api/admin/holidays?year=2027").json()]
    assert names == ["New Year", "Pongal"]
