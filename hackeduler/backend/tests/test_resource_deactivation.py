"""Scheduled resource deactivation ("inactive from" a date)."""
import uuid
from datetime import date, timedelta

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import AuditLog, EmailNotificationLog, SecurityResource
from app.services import settings_service

from .conftest import booking_payload

FROM = date(2027, 3, 8)  # Monday; resource unavailable from this date


def _today() -> date:
    db = SessionLocal()
    try:
        return settings_service.org_today(db)
    finally:
        db.close()


def _schedule(admin, data, d=FROM, reason="Engineer moving to another team", idx=0):
    return admin.patch(f"/api/admin/resources/{data['resources'][idx].id}", json={"inactive_from": d.isoformat(), "reason": reason})


def test_schedule_deactivation_keeps_resource_active_until_date(admin, req1, data):
    r = _schedule(admin, data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_active"] is True and body["inactive_from"] == "2027-03-08" and body["inactive_reason"].startswith("Engineer")
    # 5-working-day booking ending before the date is fine
    ok = req1.post("/api/bookings", json=booking_payload(data, act_idx=1))
    assert ok.status_code == 201 and ok.json()["end_date"] == "2027-03-05"


def test_bookings_reaching_the_date_are_blocked(admin, req1, data):
    _schedule(admin, data)
    crossing = req1.post("/api/bookings", json=booking_payload(data))  # 8 days: Mar 1 - Mar 10
    assert crossing.status_code == 409
    assert "unavailable from 08 Mar 2027" in crossing.json()["error"]["message"]
    after = req1.post("/api/bookings", json=booking_payload(data, start=date(2027, 3, 15), act_idx=1))
    assert after.status_code == 409
    pre = req1.post("/api/availability/check", json={"resource_id": str(data["resources"][0].id),
                                                     "activity_type_id": str(data["acts"][0].id), "start_date": "2027-03-01"}).json()
    assert pre["available"] is False and pre["reason"] == "inactive_resource"
    assert pre["suggested_start_date"] is None  # no 8-day slot fits before the date
    assert {a["display_name"] for a in pre["alternative_resources"]} == {"Resource 02", "Resource 03"}


def test_calendar_shows_inactive_from_the_date(admin, req1, data):
    _schedule(admin, data)
    cal = req1.get(f"/api/calendar?start=2027-03-04&end=2027-03-09&activity_type_id={data['acts'][0].id}").json()
    days = {c["date"]: c for c in cal["resources"][0]["days"]}
    assert days["2027-03-04"]["state"] == "limited"   # free, but an 8-day booking would cross the date
    assert days["2027-03-08"]["state"] == "inactive" and days["2027-03-09"]["state"] == "inactive"
    assert cal["resources"][0]["inactive_from"] == "2027-03-08"
    assert cal["resources"][1]["days"][4]["state"] == "available"  # other resources unaffected


def test_existing_bookings_are_flagged_not_changed(admin, req1, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/approve")
    r = _schedule(admin, data)
    assert r.status_code == 200
    got = admin.get(f"/api/admin/bookings/{b['id']}").json()
    assert got["booking"]["status"] == "approved" and got["booking"]["end_date"] == "2027-03-10"
    assert got["booking"]["needs_review"] is True
    conf = admin.get("/api/admin/conflicts").json()
    c = next(x for x in conf if x["booking_id"] == b["id"])
    assert c["conflict_type"] == "inactive_resource" and "inactive from 08 Mar 2027" in c["description"]
    assert c["conflict_start_date"] == "2027-03-08"
    db = SessionLocal()
    assert db.scalar(select(EmailNotificationLog).where(EmailNotificationLog.template_key == "booking_impacted_poc",
                                                        EmailNotificationLog.booking_id == uuid.UUID(b["id"])))
    db.close()
    # approval of a pending booking crossing the date is blocked (revalidation)
    p = req1.post("/api/bookings", json=booking_payload(data, resource_idx=1)).json()
    _schedule(admin, data, idx=1)
    ap = admin.post(f"/api/admin/bookings/{p['id']}/approve")
    assert ap.status_code == 409 and ap.json()["error"]["code"] == "override_required"


def test_validation_and_today_means_immediate(admin, data):
    today = _today()
    assert _schedule(admin, data, d=today - timedelta(days=1)).status_code == 422
    both = admin.patch(f"/api/admin/resources/{data['resources'][0].id}", json={"inactive_from": FROM.isoformat(), "is_active": False})
    assert both.status_code == 422
    r = _schedule(admin, data, d=today)
    assert r.json()["is_active"] is False and r.json()["inactive_from"] == today.isoformat()
    assert _schedule(admin, data, d=FROM).status_code == 422  # already inactive


def test_cancel_scheduled_deactivation(admin, req1, data):
    _schedule(admin, data)
    r = admin.patch(f"/api/admin/resources/{data['resources'][0].id}", json={"inactive_from": None})
    assert r.status_code == 200 and r.json()["inactive_from"] is None and r.json()["is_active"] is True
    assert req1.post("/api/bookings", json=booking_payload(data)).status_code == 201
    db = SessionLocal()
    actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity_type == "resource")).all()]
    assert "resource.deactivation_scheduled" in actions and "resource.deactivation_cancelled" in actions
    db.close()


def test_worker_applies_deactivation_on_the_date(admin, data):
    _schedule(admin, data)
    db = SessionLocal()
    today = settings_service.org_today(db)
    db.execute(update(SecurityResource).where(SecurityResource.id == data["resources"][0].id).values(inactive_from=today))
    db.commit()
    db.close()
    from app.worker import run_once

    assert run_once()["deactivated"] == 1
    res = next(r for r in admin.get("/api/admin/resources").json() if r["id"] == str(data["resources"][0].id))
    assert res["is_active"] is False and res["deactivated_at"]
    db = SessionLocal()
    a = db.scalar(select(AuditLog).where(AuditLog.action == "resource.deactivated", AuditLog.actor_email == "system"))
    assert a and "Scheduled deactivation" in a.reason and "another team" in a.reason
    db.close()
    assert run_once()["deactivated"] == 0  # idempotent


def test_reactivation_clears_dates(admin, data):
    rid = data["resources"][0].id
    admin.patch(f"/api/admin/resources/{rid}", json={"is_active": False, "reason": "Left"})
    r = admin.patch(f"/api/admin/resources/{rid}", json={"is_active": True})
    assert r.json()["is_active"] is True and r.json()["inactive_from"] is None and r.json()["inactive_reason"] is None


def test_immediate_deactivation_keeps_past_history_visible(admin, data):
    rid = data["resources"][0].id
    admin.patch(f"/api/admin/resources/{rid}", json={"is_active": False})
    today = _today()
    start = today - timedelta(days=3)
    cal = admin.get(f"/api/admin/calendar?start={start.isoformat()}&end={today.isoformat()}").json()
    states = [c["state"] for c in cal["resources"][0]["days"]]
    assert states[-1] == "inactive" and "inactive" not in states[:-1]


def test_admin_can_force_allocate_past_the_date(admin, data):
    _schedule(admin, data)
    p = booking_payload(data)
    assert admin.post("/api/admin/bookings", json=p).status_code == 409
    r = admin.post("/api/admin/bookings", json={**p, "force": {"confirm": True, "reason": "Engineer staying an extra week"}})
    assert r.status_code == 201
    conf = admin.get("/api/admin/conflicts").json()
    assert any(c["conflict_type"] == "inactive_resource" and c["booking_id"] == r.json()["id"] for c in conf)


def test_dashboard_capacity_excludes_inactive_days(admin, data):
    before = admin.get("/api/admin/dashboard?start=2027-03-01&end=2027-03-31").json()
    _schedule(admin, data)
    after = admin.get("/api/admin/dashboard?start=2027-03-01&end=2027-03-31").json()
    cap = lambda d: next(m for m in d["charts"]["monthly_utilization"] if m["month"] == "2027-03")["capacity_days"]  # noqa: E731
    assert cap(before) - cap(after) == 18  # Resource 01 loses Mar 8-31 (18 working days)


def test_requester_cannot_schedule_deactivation(req1, data):
    r = req1.patch(f"/api/admin/resources/{data['resources'][0].id}", json={"inactive_from": FROM.isoformat()})
    assert r.status_code == 403


