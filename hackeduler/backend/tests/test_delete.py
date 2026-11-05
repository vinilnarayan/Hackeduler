"""Deleting users and resources: removed when unused, archived when referenced by history."""
import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, ResourceLeave, SecurityResource, User

from .conftest import PASSWORD, booking_payload


def _login(email):
    from app.main import app

    return TestClient(app).post("/api/auth/login", json={"email": email, "password": PASSWORD})


# ---------------------------------------------------------------- users
def test_delete_unused_user_removes_it(admin):
    u = admin.post("/api/admin/users", json={"email": "temp@test.local", "full_name": "Temp", "role": "requester", "password": PASSWORD}).json()
    r = admin.delete(f"/api/admin/users/{u['id']}")
    assert r.status_code == 200 and r.json()["mode"] == "removed"
    db = SessionLocal()
    assert db.get(User, uuid.UUID(u["id"])) is None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "user.deleted")).new_value == {"mode": "removed"}
    db.close()


def test_delete_user_with_bookings_archives_and_keeps_history(admin, req1, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    uid = str(data["users"]["req1"].id)
    r = admin.delete(f"/api/admin/users/{uid}")
    assert r.json()["mode"] == "archived"
    assert uid not in [u["id"] for u in admin.get("/api/admin/users").json()]
    assert uid in [u["id"] for u in admin.get("/api/admin/users?include_deleted=true").json()]
    assert req1.get("/api/auth/me").status_code == 401           # existing session revoked
    assert _login("req1@test.local").status_code == 401           # cannot sign in
    hist = admin.get(f"/api/admin/bookings/{b['id']}").json()["booking"]
    assert hist["requester_name"] == "Req One"                    # history intact
    # email can be reused; then the archived account can't be restored
    assert admin.post("/api/admin/users", json={"email": "req1@test.local", "full_name": "New", "role": "requester", "password": PASSWORD}).status_code == 201
    assert _login("req1@test.local").status_code == 200
    assert admin.post(f"/api/admin/users/{uid}/restore").status_code == 409


def test_restore_archived_user(admin, req1, data):
    req1.post("/api/bookings", json=booking_payload(data))
    uid = str(data["users"]["req1"].id)
    admin.delete(f"/api/admin/users/{uid}")
    r = admin.post(f"/api/admin/users/{uid}/restore")
    assert r.status_code == 200 and r.json()["deleted_at"] is None and r.json()["is_active"] is False
    admin.patch(f"/api/admin/users/{uid}", json={"is_active": True})
    assert _login("req1@test.local").status_code == 200


def test_delete_guards(admin, req1, data):
    assert admin.delete(f"/api/admin/users/{data['users']['admin'].id}").status_code == 422   # cannot delete yourself
    assert req1.delete(f"/api/admin/users/{data['users']['req2'].id}").status_code == 403    # admins only
    # another admin can be deleted (the acting admin remains)
    other = admin.post("/api/admin/users", json={"email": "a2@test.local", "full_name": "A2", "role": "admin",
                                                 "password": PASSWORD}).json()
    assert admin.delete(f"/api/admin/users/{other['id']}").status_code == 200


# ---------------------------------------------------------------- resources
def test_delete_unused_resource_removes_it_and_its_leave(admin, data):
    rid = data["resources"][2].id
    admin.post("/api/admin/leaves", json={"resource_id": str(rid), "start_date": "2027-03-01", "end_date": "2027-03-02"})
    r = admin.delete(f"/api/admin/resources/{rid}")
    assert r.status_code == 200 and r.json()["mode"] == "removed"
    db = SessionLocal()
    assert db.get(SecurityResource, rid) is None
    assert db.scalars(select(ResourceLeave).where(ResourceLeave.resource_id == rid)).first() is None
    db.close()


def test_delete_resource_blocked_by_active_bookings(admin, req1, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    r = admin.delete(f"/api/admin/resources/{data['resources'][0].id}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "resource_in_use"
    assert r.json()["error"]["details"]["bookings"][0]["id"] == b["id"]


def test_delete_resource_with_history_archives(admin, req1, data):
    rid = data["resources"][0].id
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    admin.post(f"/api/admin/bookings/{b['id']}/reject", json={"reason": "No"})
    r = admin.delete(f"/api/admin/resources/{rid}")
    assert r.json()["mode"] == "archived"
    assert str(rid) not in [x["id"] for x in admin.get("/api/admin/resources").json()]
    assert str(rid) not in [x["id"] for x in req1.get("/api/resources").json()]
    cal = req1.get("/api/calendar?start=2027-03-01&end=2027-03-05").json()
    assert [x["display_name"] for x in cal["resources"]] == ["Resource 02", "Resource 03"]
    assert req1.post("/api/bookings", json=booking_payload(data, start=date(2027, 4, 5))).status_code == 404
    assert admin.get(f"/api/admin/bookings/{b['id']}").json()["booking"]["resource_display_name"] == "Resource 01"
    # identifiers are never reused
    new = admin.post("/api/admin/resources", json={"engineer_name": "New Engineer"}).json()
    assert new["display_name"] == "Resource 04"
    # restore brings it back inactive
    res = admin.post(f"/api/admin/resources/{rid}/restore").json()
    assert res["deleted_at"] is None and res["is_active"] is False


def test_requester_cannot_delete_resource(req1, data):
    assert req1.delete(f"/api/admin/resources/{data['resources'][0].id}").status_code == 403
