"""Activity types: hidden-from-requesters flag and Remove (delete / archive)."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ActivityType, AuditLog

from .conftest import booking_payload


def _hide(admin, act):
    r = admin.patch(f"/api/admin/activity-types/{act.id}", json={"visible_to_requesters": False})
    assert r.status_code == 200 and r.json()["visible_to_requesters"] is False


def test_new_types_are_visible_by_default(admin, req1):
    r = admin.post("/api/admin/activity-types", json={"name": "Red Team", "base_duration_days": 10})
    assert r.status_code == 201 and r.json()["visible_to_requesters"] is True
    assert "Red Team" in [a["name"] for a in req1.get("/api/activity-types").json()]


def test_hidden_type_not_listed_for_requesters_but_listed_for_admins(admin, req1, data):
    r = admin.post("/api/admin/activity-types", json={"name": "Internal Only", "base_duration_days": 3, "visible_to_requesters": False})
    assert r.status_code == 201
    assert "Internal Only" not in [a["name"] for a in req1.get("/api/activity-types").json()]
    assert "Internal Only" in [a["name"] for a in admin.get("/api/admin/activity-types").json()]


def test_requester_cannot_book_or_preview_hidden_type(admin, req1, data):
    _hide(admin, data["acts"][0])
    assert req1.post("/api/bookings", json=booking_payload(data)).status_code == 422
    assert req1.post("/api/availability/check", json={"resource_id": str(data["resources"][0].id),
                                                      "activity_type_id": str(data["acts"][0].id),
                                                      "start_date": "2027-03-01"}).status_code == 422
    assert req1.post("/api/availability/auto", json={"activity_type_id": str(data["acts"][0].id),
                                                     "start_date": "2027-03-01"}).status_code == 422
    # other types are unaffected
    assert req1.post("/api/bookings", json=booking_payload(data, act_idx=1)).status_code == 201


def test_admin_can_still_book_and_preview_hidden_type(admin, data):
    _hide(admin, data["acts"][0])
    assert admin.post("/api/availability/auto", json={"activity_type_id": str(data["acts"][0].id),
                                                      "start_date": "2027-03-01"}).status_code == 200
    assert admin.post("/api/admin/bookings", json=booking_payload(data)).status_code in (200, 201)


def test_visibility_change_is_audited(admin, data):
    _hide(admin, data["acts"][0])
    db = SessionLocal()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "activity_type.visibility_changed")) is not None
    db.close()


def test_remove_unused_type_deletes_it(admin, data):
    a = admin.post("/api/admin/activity-types", json={"name": "Temp", "base_duration_days": 2}).json()
    r = admin.delete(f"/api/admin/activity-types/{a['id']}")
    assert r.status_code == 200 and r.json()["mode"] == "removed"
    db = SessionLocal()
    assert db.get(ActivityType, uuid.UUID(a["id"])) is None
    db.close()
    assert admin.delete(f"/api/admin/activity-types/{a['id']}").status_code == 404


def test_remove_used_type_archives_and_keeps_history(admin, req1, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    act = data["acts"][0]
    r = admin.delete(f"/api/admin/activity-types/{act.id}")
    assert r.json()["mode"] == "archived"
    assert str(act.id) not in [a["id"] for a in admin.get("/api/admin/activity-types").json()]
    assert str(act.id) in [a["id"] for a in admin.get("/api/admin/activity-types?include_deleted=true").json()]
    assert str(act.id) not in [a["id"] for a in req1.get("/api/activity-types").json()]
    # cannot be booked, edited; existing booking intact
    assert req1.post("/api/bookings", json=booking_payload(data, start=__import__("datetime").date(2027, 4, 5))).status_code == 422
    assert admin.patch(f"/api/admin/activity-types/{act.id}", json={"name": "x"}).status_code == 404
    detail = admin.get(f"/api/admin/bookings/{b['id']}")
    assert detail.status_code == 200
    # the name can be reused afterwards
    assert admin.post("/api/admin/activity-types", json={"name": act.name, "base_duration_days": act.base_duration_days}).status_code == 201


def test_remove_requires_admin(req1, data):
    assert req1.delete(f"/api/admin/activity-types/{data['acts'][0].id}").status_code == 403


def test_remove_unknown_type_is_404(admin):
    assert admin.delete(f"/api/admin/activity-types/{uuid.uuid4()}").status_code == 404


def test_removed_builtin_type_does_not_come_back_after_reseed(admin, data):
    """HACKEDULER_SEED=minimal re-runs the seed on every deploy; a removed built-in type must stay removed."""
    from app.seed import seed_reference

    admin_list = lambda: admin.get("/api/admin/activity-types").json()  # noqa: E731
    seed_reference(SessionLocal())
    target = next(a for a in admin_list() if a["name"] == "Web Application PT")   # unused: would be erased outright
    r = admin.delete(f"/api/admin/activity-types/{target['id']}")
    assert r.status_code == 200 and r.json()["mode"] == "archived"
    seed_reference(SessionLocal())
    seed_reference(SessionLocal())
    assert target["id"] not in [a["id"] for a in admin_list()]
    assert not [a for a in admin_list() if a["name"] == "Web Application PT"]
