"""The 'resource' role: sees only its own assigned bookings, records report sharing, manages own leave."""
import re
import uuid
from datetime import date, timedelta

from app.main import app
from app.routers import requester as requester_router

from .conftest import MON, PASSWORD, Api, booking_payload


def _make_resource_user(admin, resource, email="eng1@test.local"):
    r = admin.post("/api/admin/users", json={"email": email, "full_name": "Eng One", "password": PASSWORD,
                                             "role": "resource", "resource_id": str(resource.id)})
    assert r.status_code == 201, r.text
    return r.json()


def _booking(admin, data, resource_idx=0, start=MON, **kw):
    r = admin.post("/api/admin/bookings", json=booking_payload(data, resource_idx=resource_idx, start=start, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def test_admin_creates_resource_user_linked_to_a_resource(admin, data):
    u = _make_resource_user(admin, data["resources"][0])
    assert u["role"] == "resource" and u["resource_id"] == str(data["resources"][0].id)
    me = Api("eng1@test.local").get("/api/auth/me").json()["user"]
    assert me["role"] == "resource" and me["resource_name"] == "Resource 01"


def test_resource_role_needs_a_resource_and_each_resource_has_one_user(admin, data):
    r = admin.post("/api/admin/users", json={"email": "x@test.local", "full_name": "X", "password": PASSWORD, "role": "resource"})
    assert r.status_code == 422
    _make_resource_user(admin, data["resources"][0])
    r = admin.post("/api/admin/users", json={"email": "y@test.local", "full_name": "Y", "password": PASSWORD,
                                             "role": "resource", "resource_id": str(data["resources"][0].id)})
    assert r.status_code == 409
    r = admin.post("/api/admin/users", json={"email": "z@test.local", "full_name": "Z", "password": PASSWORD,
                                             "role": "requester", "resource_id": str(data["resources"][0].id)})
    assert r.status_code == 201 and r.json()["resource_id"] is None   # link only applies to the resource role


def test_resource_sees_only_own_bookings(admin, data):
    mine = _booking(admin, data, 0)
    other = _booking(admin, data, 1, application_name="Other App")
    _make_resource_user(admin, data["resources"][0])
    eng = Api("eng1@test.local")
    ids = {b["id"] for b in eng.get("/api/resource/bookings").json()["items"]}
    assert ids == {mine["id"]}
    assert eng.get(f"/api/resource/bookings/{mine['id']}").status_code == 200
    assert eng.get(f"/api/resource/bookings/{other['id']}").status_code == 404
    assert eng.put(f"/api/resource/bookings/{other['id']}/report", json={"report_shared": True, "report_type": "V1"}).status_code == 404


def test_resource_sees_bookings_where_it_is_an_extra_resource(admin, data):
    r = admin.post("/api/admin/bookings", json=booking_payload(
        data, additional_resource_ids=[str(data["resources"][1].id)]))
    assert r.status_code == 201, r.text
    _make_resource_user(admin, data["resources"][1])
    ids = {x["id"] for x in Api("eng1@test.local").get("/api/resource/bookings").json()["items"]}
    assert r.json()["id"] in ids


def test_report_sharing_and_visibility_to_everyone(admin, req1, data):
    r = req1.post("/api/bookings", json=booking_payload(data))
    assert r.status_code == 201
    bid = r.json()["id"]
    _make_resource_user(admin, data["resources"][0])
    eng = Api("eng1@test.local")
    assert eng.get("/api/resource/bookings").json()["total"] == 0          # pending: not assigned yet
    assert admin.post(f"/api/admin/bookings/{bid}/approve", json={}).status_code == 200
    assert eng.get("/api/resource/bookings").json()["total"] == 1

    # validation
    assert eng.put(f"/api/resource/bookings/{bid}/report", json={"report_shared": True}).status_code == 422
    assert eng.put(f"/api/resource/bookings/{bid}/report", json={"report_shared": True, "report_type": "Other"}).status_code == 422

    r = eng.put(f"/api/resource/bookings/{bid}/report", json={"report_shared": True, "report_type": "V1", "report_comments": "Sent to POC\nall good"})
    assert r.status_code == 200
    j = r.json()
    assert j["report_shared"] is True and j["report_type"] == "V1" and j["report_comments"] == "Sent to POC\nall good"
    assert j["report_shared_at"]

    # the requester sees it (read-only), and the admin list shows it
    mine = {b["id"]: b for b in req1.get("/api/bookings/mine").json()}
    assert mine[bid]["report_shared"] is True and mine[bid]["report_type"] == "V1"
    adm = {b["id"]: b for b in admin.get("/api/admin/bookings").json()["items"]}
    assert adm[bid]["report_shared"] is True and adm[bid]["report_type"] == "V1"
    # requester cannot modify it
    assert req1.put(f"/api/admin/bookings/{bid}/report", json={"report_shared": False}).status_code == 403
    assert req1.put(f"/api/resource/bookings/{bid}/report", json={"report_shared": False}).status_code == 403

    # admin can change it too (Met), and un-share
    r = admin.put(f"/api/admin/bookings/{bid}/report", json={"report_shared": True, "report_type": "Met"})
    assert r.status_code == 200 and r.json()["report_type"] == "Met"
    r = eng.put(f"/api/resource/bookings/{bid}/report", json={"report_shared": False, "report_comments": "recalled"})
    assert r.status_code == 200 and r.json()["report_shared"] is False and r.json()["report_shared_at"] is None

    # audited
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import AuditLog

    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.action == "booking.report_updated")).all()
    assert len(rows) == 3 and {r.actor_role for r in rows} == {"resource", "admin"}


def test_report_not_allowed_on_pending_or_cancelled(admin, req1, data):
    bid = req1.post("/api/bookings", json=booking_payload(data)).json()["id"]
    r = admin.put(f"/api/admin/bookings/{bid}/report", json={"report_shared": True, "report_type": "V1"})
    assert r.status_code == 422


def test_resource_cannot_change_anything_else(admin, data):
    b = _booking(admin, data, 0)
    _make_resource_user(admin, data["resources"][0])
    eng = Api("eng1@test.local")
    for method in ("patch", "post", "delete"):
        r = getattr(eng, method)(f"/api/resource/bookings/{b['id']}", **({"json": {}} if method != "delete" else {}))
        assert r.status_code in (404, 405), (method, r.status_code)
    assert eng.get(f"/api/admin/bookings/{b['id']}").status_code == 403


def test_resource_user_is_refused_on_admin_and_requester_endpoints(admin, data):
    _make_resource_user(admin, data["resources"][0])
    eng = Api("eng1@test.local")
    leaks = []
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api/admin"):
            for m in ops:
                if m.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    p = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
                    r = eng.c.request(m.upper(), p, json={} if m != "get" else None, headers={"X-CSRF-Token": eng.csrf})
                    if r.status_code != 403:
                        leaks.append((m, p, r.status_code))
    n = 0
    for route in requester_router.router.routes:
        for m in route.methods:
            n += 1
            p = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), route.path)
            r = eng.c.request(m, p, json={} if m != "GET" else None, headers={"X-CSRF-Token": eng.csrf})
            if r.status_code != 403:
                leaks.append((m, p, r.status_code))
    assert n > 10
    assert not leaks, leaks


def test_requesters_and_admins_are_refused_on_resource_endpoints(admin, req1, data):
    leaks = []
    for client in (admin, req1):
        for path, ops in app.openapi()["paths"].items():
            if path.startswith("/api/resource/"):
                for m in ops:
                    p = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
                    r = client.c.request(m.upper(), p, json={} if m != "get" else None, headers={"X-CSRF-Token": client.csrf})
                    if r.status_code != 403:
                        leaks.append((m, p, r.status_code))
    assert not leaks, leaks


def test_resource_leave_add_list_cancel_only_own(admin, data):
    _make_resource_user(admin, data["resources"][0])
    eng = Api("eng1@test.local")
    s, e = date.today() + timedelta(days=10), date.today() + timedelta(days=12)
    r = eng.post("/api/resource/leaves", json={"start_date": s.isoformat(), "end_date": e.isoformat(), "leave_type": "Annual"})
    assert r.status_code == 201, r.text
    lid = r.json()["leave"]["id"]
    assert [x["id"] for x in eng.get("/api/resource/leaves").json()] == [lid]
    # admin sees it against the right resource
    al = admin.get("/api/admin/leaves").json()
    assert [x["id"] for x in al] == [lid] and al[0]["resource_id"] == str(data["resources"][0].id)
    # validation: past and reversed dates
    assert eng.post("/api/resource/leaves", json={"start_date": "2020-01-01", "end_date": "2020-01-02"}).status_code == 422
    assert eng.post("/api/resource/leaves", json={"start_date": e.isoformat(), "end_date": s.isoformat()}).status_code == 422
    # the resource id cannot be supplied by the caller
    assert eng.post("/api/resource/leaves", json={"start_date": s.isoformat(), "end_date": e.isoformat(),
                                                  "resource_id": str(data["resources"][1].id)}).status_code == 422
    # someone else's leave cannot be cancelled
    other = admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][1].id), "start_date": s.isoformat(), "end_date": e.isoformat()}).json()["leave"]["id"]
    assert eng.delete(f"/api/resource/leaves/{other}").status_code == 404
    assert eng.delete(f"/api/resource/leaves/{lid}").status_code == 200
    assert eng.get("/api/resource/leaves").json() == []


def test_leave_over_a_booking_raises_a_conflict_for_admin(admin, data):
    b = _booking(admin, data, 0)
    _make_resource_user(admin, data["resources"][0])
    eng = Api("eng1@test.local")
    d = date.fromisoformat(b["start_date"])
    # test data is in 2027; use the booking's own dates (future relative to today)
    r = eng.post("/api/resource/leaves", json={"start_date": d.isoformat(), "end_date": d.isoformat()})
    assert r.status_code == 201 and r.json()["flagged_bookings"] >= 1
    assert admin.get("/api/admin/bookings").json()["items"][0]["open_conflicts"] >= 1


def test_dashboard_counts(admin, data):
    b = _booking(admin, data, 0)
    _booking(admin, data, 1, application_name="Other")
    _make_resource_user(admin, data["resources"][0])
    eng = Api("eng1@test.local")
    eng.post("/api/resource/leaves", json={"start_date": (date.today() + timedelta(days=5)).isoformat(),
                                           "end_date": (date.today() + timedelta(days=6)).isoformat()})
    d = eng.get("/api/resource/dashboard").json()
    assert d["counts"]["assigned"] == 1 and d["counts"]["upcoming"] == 1 and d["counts"]["upcoming_leaves"] == 1
    assert d["counts"]["reports_shared"] == 0 and d["upcoming"][0]["id"] == b["id"]


def test_demoting_the_last_admin_via_role_change_is_refused(admin, data):
    users = {u["email"]: u for u in admin.get("/api/admin/users").json()}
    r = admin.patch(f"/api/admin/users/{users['admin@test.local']['id']}", json={"role": "resource", "resource_id": str(data["resources"][0].id)})
    assert r.status_code == 422
