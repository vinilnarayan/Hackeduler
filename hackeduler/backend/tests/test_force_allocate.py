"""Force Allocate: admin-only, reason + warning + explicit confirmation, never modifies other bookings,
immutable audit trail (criteria 18-22, 25)."""
import uuid
from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.errors import ServiceError
from app.models import AuditLog, BookingResourceLock, User
from app.services import booking_service

from .conftest import MON, booking_payload

FORCE = {"confirm": True, "reason": "CISO-approved emergency assessment"}


def _setup_conflict(req1, admin, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    return b


def test_non_admin_cannot_invoke_force_via_any_api(req1, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    # direct admin API calls -> 403
    assert req1.post("/api/admin/bookings", json={**booking_payload(data), "force": FORCE}).status_code == 403
    assert req1.patch(f"/api/admin/bookings/{b['id']}", json={"start_date": "2027-03-02", "reason": "x", "force": FORCE}).status_code == 403
    assert req1.post(f"/api/admin/bookings/{b['id']}/approve", json={"force": FORCE}).status_code == 403
    # smuggling force into requester endpoints is rejected (extra fields forbidden)
    assert req1.post("/api/bookings", json={**booking_payload(data, start=date(2027, 3, 2)), "force": FORCE}).status_code == 422
    assert req1.post(f"/api/bookings/{b['id']}/change-requests",
                     json={"request_type": "reschedule", "reason": "x", "proposed_start_date": "2027-03-02",
                           "force": FORCE}).status_code == 422
    # client-side header manipulation does nothing
    assert req1.post("/api/admin/bookings", json={**booking_payload(data), "force": FORCE},
                     headers={"X-Role": "admin", "X-Force-Allocate": "1"}).status_code == 403
    db = SessionLocal()
    denials = db.scalars(select(AuditLog).where(AuditLog.action.in_(("authorization.denied", "force_allocate.denied")))).all()
    assert len(denials) >= 4
    db.close()


def test_service_layer_also_rejects_non_admin_force(data):
    db = SessionLocal()
    user = db.get(User, data["users"]["req1"].id)
    try:
        booking_service.ensure_force_allowed(user, booking_service.ForceOptions(True, "x"))
        raise AssertionError("should have raised")
    except ServiceError as e:
        assert e.status_code == 403
    db.close()


def test_force_requires_warning_reason_and_confirmation(req1, admin, data):
    existing = _setup_conflict(req1, admin, data)
    p = booking_payload(data, start=date(2027, 3, 3), application_name="Emergency")
    r = admin.post("/api/admin/bookings", json=p)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "override_required" and err["details"]["requires_force"] is True
    assert err["details"]["warning"].startswith("Warning: This allocation conflicts")
    assert err["details"]["conflicting_bookings"][0]["id"] == existing["id"]
    assert admin.post("/api/admin/bookings", json={**p, "force": {"confirm": False, "reason": "x"}}).status_code == 422
    assert admin.post("/api/admin/bookings", json={**p, "force": {"confirm": True, "reason": "  "}}).status_code == 422
    assert admin.post("/api/admin/bookings", json={**p, "force": {"confirm": True}}).status_code == 422


def test_force_allocate_never_modifies_other_booking(req1, admin, data):
    existing = _setup_conflict(req1, admin, data)
    before = admin.get(f"/api/admin/bookings/{existing['id']}").json()["booking"]
    p = booking_payload(data, start=date(2027, 3, 3), application_name="Emergency")
    r = admin.post("/api/admin/bookings", json={**p, "force": FORCE})
    assert r.status_code == 201, r.text
    forced = r.json()
    assert forced["is_force_allocated"] is True and forced["needs_review"] is True
    after = admin.get(f"/api/admin/bookings/{existing['id']}").json()
    ab = after["booking"]
    for k in ("status", "start_date", "end_date", "resource_id", "duration_days", "application_name"):
        assert ab[k] == before[k], k
    assert ab["needs_review"] is True
    assert sum(1 for lk in after["locks"] if lk["lock_status"] == "confirmed") == 8
    # both reservations coexist on the overlapping dates; overlap is visible
    db = SessionLocal()
    n = db.scalars(select(BookingResourceLock).where(BookingResourceLock.work_date == date(2027, 3, 3),
                                                     BookingResourceLock.lock_status.in_(("pending", "confirmed")))).all()
    assert len(n) == 2
    db.close()
    cal = admin.get("/api/admin/calendar?start=2027-03-03&end=2027-03-03").json()
    assert cal["resources"][0]["days"][0]["conflict"] is True
    # conflicts recorded and open until resolved
    confs = admin.get("/api/admin/conflicts?status=open").json()
    types = {c["conflict_type"] for c in confs}
    assert {"overlapping_booking", "manual_override"} <= types
    ov = next(c for c in confs if c["conflict_type"] == "overlapping_booking")
    assert ov["booking_id"] == forced["id"] and ov["conflicting_booking_id"] == existing["id"]
    # affected POC notified
    db = SessionLocal()
    from app.models import EmailNotificationLog

    assert db.scalar(select(EmailNotificationLog).where(EmailNotificationLog.template_key == "booking_impacted_poc",
                                                        EmailNotificationLog.booking_id == uuid.UUID(existing["id"])))
    db.close()
    # normal requests are still blocked on those dates
    assert req1.post("/api/bookings", json=booking_payload(data, start=date(2027, 3, 11))).status_code == 409


def test_force_allocate_is_audited_with_full_detail(req1, admin, data):
    existing = _setup_conflict(req1, admin, data)
    r = admin.post("/api/admin/bookings", json={**booking_payload(data, start=date(2027, 3, 3)), "force": FORCE})
    fid = r.json()["id"]
    db = SessionLocal()
    a = db.scalar(select(AuditLog).where(AuditLog.action == "booking.force_allocated"))
    assert a.actor_email == "admin@test.local" and a.reason == FORCE["reason"]
    assert a.booking_id == uuid.UUID(fid)
    assert existing["id"] in a.new_value["conflicting_booking_ids"]
    assert "2027-03-03" in a.new_value["affected_dates"]
    assert a.new_value["allocation"]["resource_code"] == "RES-01"
    assert a.request_id
    db.close()


def test_force_reassign_records_previous_allocation(req1, req2, admin, data):
    a = req1.post("/api/bookings", json=booking_payload(data)).json()
    b = req2.post("/api/bookings", json=booking_payload(data, resource_idx=1)).json()
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"resource_id": str(data["resources"][0].id), "reason": "swap"})
    assert r.status_code == 409
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"resource_id": str(data["resources"][0].id), "reason": "swap",
                                                            "force": FORCE})
    assert r.status_code == 200
    d = admin.get(f"/api/admin/bookings/{b['id']}").json()
    fa = next(x for x in d["audit"] if x["action"] == "booking.force_allocated")
    assert fa["previous_value"]["allocation"]["resource_code"] == "RES-02"
    assert fa["new_value"]["allocation"]["resource_code"] == "RES-01"
    assert req1.get(f"/api/bookings/{a['id']}").json()["start_date"] == MON.isoformat()


def test_force_on_weekend_start(admin, data):
    p = booking_payload(data, start=date(2027, 3, 6))
    assert admin.post("/api/admin/bookings", json=p).status_code == 409
    r = admin.post("/api/admin/bookings", json={**p, "force": FORCE})
    assert r.status_code == 201 and r.json()["start_date"] == "2027-03-06"
