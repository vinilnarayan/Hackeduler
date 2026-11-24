"""Admin 'Act as': an administrator works inside another user's pages, audited, time-limited, with guard rails."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, User

from .conftest import PASSWORD, Api, booking_payload


def _uid(email):
    with SessionLocal() as db:
        return str(db.scalars(select(User).where(User.email == email)).one().id)


def _start(admin, email):
    r = admin.post(f"/api/auth/act-as/{_uid(email)}")
    if r.status_code == 200:
        admin.csrf = r.json()["csrf_token"]
    return r


def test_admin_acts_as_requester_books_and_exits(admin, data):
    r = _start(admin, "req1@test.local")
    assert r.status_code == 200 and r.json()["user"]["email"] == "req1@test.local"
    me = admin.get("/api/auth/me").json()
    assert me["user"]["role"] == "requester" and me["acting_as"]["admin_email"] == "admin@test.local"

    # works through the requester's own flow and is stored against the requester
    b = admin.post("/api/bookings", json=booking_payload(data))
    assert b.status_code == 201, b.text
    assert b.json()["requester_name"] and len(admin.get("/api/bookings/mine").json()) == 1
    # but cannot use admin endpoints while acting
    assert admin.get("/api/admin/bookings").status_code == 403

    # audit: actor is the requester, real admin recorded
    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.acted_by_email == "admin@test.local")).all()
        actions = {a.action for a in rows}
        assert "booking.created" in actions or any(a.entity_type == "booking" for a in rows)
        assert all(a.actor_email in ("req1@test.local", "admin@test.local") for a in rows)
        assert db.scalars(select(AuditLog).where(AuditLog.action == "admin.act_as_started")).one().actor_email == "admin@test.local"

    ex = admin.post("/api/auth/act-as/exit")
    assert ex.status_code == 200 and ex.json()["user"]["email"] == "admin@test.local"
    admin.csrf = ex.json()["csrf_token"]
    me = admin.get("/api/auth/me").json()
    assert me["user"]["role"] == "admin" and me["acting_as"] is None
    assert admin.get("/api/admin/bookings").status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(AuditLog).where(AuditLog.action == "admin.act_as_ended")).one().acted_by_email == "admin@test.local"


def test_guard_rails(admin, req1, data):
    # only admins can start; no self, no other admin, no disabled user, no unknown user
    assert req1.post(f"/api/auth/act-as/{_uid('admin@test.local')}").status_code == 403
    assert admin.post(f"/api/auth/act-as/{_uid('admin@test.local')}").status_code == 422
    assert admin.post("/api/auth/act-as/00000000-0000-0000-0000-000000000000").status_code == 404
    other = admin.post("/api/admin/users", json={"email": "adm2@test.local", "full_name": "A2", "password": PASSWORD, "role": "admin"})
    assert other.status_code == 201
    assert admin.post(f"/api/auth/act-as/{other.json()['id']}").status_code == 422
    uid = _uid("req2@test.local")
    assert admin.patch(f"/api/admin/users/{uid}", json={"is_active": False}).status_code == 200
    assert admin.post(f"/api/auth/act-as/{uid}").status_code == 422

    # while acting: cannot nest, cannot change the user's password, exiting twice is rejected
    assert _start(admin, "req1@test.local").status_code == 200
    assert admin.post(f"/api/auth/act-as/{_uid('req2@test.local')}").status_code == 403
    assert admin.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "An0ther!LongPassword"}).status_code == 403
    ex = admin.post("/api/auth/act-as/exit")
    admin.csrf = ex.json()["csrf_token"]
    assert admin.post("/api/auth/act-as/exit").status_code == 422


def test_sign_out_while_acting_keeps_target_sessions_and_returns_to_admin(admin, req1, data):
    assert _start(admin, "req1@test.local").status_code == 200
    r = admin.post("/api/auth/logout")
    assert r.status_code == 200 and r.json().get("acting_ended") is True
    admin.csrf = r.json()["csrf_token"]
    assert admin.get("/api/auth/me").json()["user"]["role"] == "admin"
    assert req1.get("/api/auth/me").status_code == 200          # the requester's own session was not revoked


def test_acting_ends_if_admin_loses_admin_rights(admin, data):
    assert _start(admin, "req1@test.local").status_code == 200
    with SessionLocal() as db:
        a = db.scalars(select(User).where(User.email == "admin@test.local")).one()
        a.token_version += 1
        db.commit()
    assert admin.get("/api/auth/me").status_code == 401
