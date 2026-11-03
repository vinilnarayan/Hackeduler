"""Authentication, CSRF and role-based access control (criteria 16-19)."""
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog

from .conftest import PASSWORD, Api, booking_payload


def test_login_and_me(req1):
    r = req1.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "requester"


def test_bad_password_rejected_and_audited(data):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "req1@test.local", "password": "wrong"})
    assert r.status_code == 401
    db = SessionLocal()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.login_failed")) is not None
    db.close()


def test_unauthenticated_is_401(data):
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/api/calendar?start=2027-03-01&end=2027-03-07").status_code == 401


def test_csrf_required_for_unsafe_methods(req1, data):
    r = req1.c.post("/api/bookings", json=booking_payload(data))  # no X-CSRF-Token header
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"


ADMIN_ENDPOINTS = [
    ("get", "/api/admin/resources"),
    ("get", "/api/admin/bookings"),
    ("get", "/api/admin/audit"),
    ("get", "/api/admin/conflicts"),
    ("get", "/api/admin/dashboard"),
    ("get", "/api/admin/calendar?start=2027-03-01&end=2027-03-07"),
    ("get", "/api/admin/leaves"),
    ("get", "/api/admin/settings"),
    ("get", "/api/admin/reports/bookings.csv"),
    ("post", "/api/admin/holidays"),
    ("post", "/api/admin/resources"),
]


@pytest.mark.parametrize("method,url", ADMIN_ENDPOINTS)
def test_requester_cannot_access_admin_endpoints(req1, method, url):
    r = getattr(req1, method)(url, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 403


def test_admin_denial_is_audited(req1):
    req1.get("/api/admin/resources")
    db = SessionLocal()
    row = db.scalar(select(AuditLog).where(AuditLog.action == "authorization.denied"))
    assert row is not None and row.actor_email == "req1@test.local"
    db.close()


def test_role_comes_from_database_not_token(req1, data):
    """Changing the role claim client-side is impossible (signed) and irrelevant (role reloaded from DB)."""
    import jwt

    token = req1.c.cookies.get("orp_session")
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["role"] = "admin"
    forged = jwt.encode(claims, "attacker-key-attacker-key-attacker-key-0000", algorithm="HS256")
    req1.c.cookies.set("orp_session", forged)
    assert req1.get("/api/admin/resources").status_code == 401


def test_logout_revokes_session(req1):
    old = req1.c.cookies.get("orp_session")
    assert req1.post("/api/auth/logout").status_code == 200
    req1.c.cookies.set("orp_session", old)
    assert req1.get("/api/auth/me").status_code == 401


def test_requester_resource_listing_is_anonymous(req1):
    body = req1.get("/api/resources").text
    assert "Secret Engineer" not in body and "eng1@offsec.local" not in body
    assert "Resource 01" in body


def test_requester_calendar_hides_engineer_names(req1, admin, data):
    admin_body = admin.get("/api/admin/calendar?start=2027-03-01&end=2027-03-31").text
    assert "Secret Engineer 1" in admin_body
    r = req1.get("/api/calendar?start=2027-03-01&end=2027-03-31")
    assert r.status_code == 200
    assert "Secret Engineer" not in r.text and "eng1@" not in r.text
    assert [x["display_name"] for x in r.json()["resources"]] == ["Resource 01", "Resource 02", "Resource 03"]


def test_requester_cannot_see_other_requesters_booking(req1, req2, data):
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert req2.get(f"/api/bookings/{b['id']}").status_code == 404
    assert req2.get(f"/api/bookings/{b['id']}/history").status_code == 404
    assert req2.post(f"/api/bookings/{b['id']}/cancel", json={"reason": "x"}).status_code == 404
    assert req2.post(f"/api/bookings/{b['id']}/change-requests",
                     json={"request_type": "cancel", "reason": "x"}).status_code == 404
    assert all(x["id"] != b["id"] for x in req2.get("/api/bookings/mine").json())
    # calendar shows the slot as reserved, but without booking details for other requesters
    cal = req2.get("/api/calendar?start=2027-03-01&end=2027-03-05").json()
    cell = cal["resources"][0]["days"][0]
    assert cell["state"] == "reserved" and "bookings" not in cell and "Customer Portal" not in str(cal)
    own = req1.get("/api/calendar?start=2027-03-01&end=2027-03-05").json()["resources"][0]["days"][0]
    assert own["mine"] is True and own["bookings"][0]["id"] == b["id"]


def test_requester_booking_output_has_no_engineer(req1, data):
    r = req1.post("/api/bookings", json=booking_payload(data))
    assert r.status_code == 201
    assert "Secret Engineer" not in r.text and "engineer" not in r.text


def test_admin_can_create_users_and_password_policy(admin):
    r = admin.post("/api/admin/users", json={"email": "new@test.local", "full_name": "N", "password": "weakweakweak", "role": "requester"})
    assert r.status_code == 422
    r = admin.post("/api/admin/users", json={"email": "new@test.local", "full_name": "N", "password": PASSWORD, "role": "requester"})
    assert r.status_code == 201
    Api("new@test.local")


def test_requester_cannot_access_audit_records(req1, data):
    req1.post("/api/bookings", json=booking_payload(data))
    assert req1.get("/api/admin/audit").status_code == 403
    hist = req1.get(f"/api/bookings/mine").json()[0]
    h = req1.get(f"/api/bookings/{hist['id']}/history").json()
    assert "actor_email" not in str(h) and "ip_address" not in str(h)


def test_security_headers(req1):
    r = req1.get("/api/auth/me")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers.get("X-Request-ID")


