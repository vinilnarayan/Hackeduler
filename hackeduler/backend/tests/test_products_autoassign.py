"""Automatic resource assignment, activities without a resource, and products/implementations."""
import threading
import uuid
from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.errors import ServiceError
from app.models import BookingResourceLock, User
from app.services import booking_service

from .conftest import MON, PASSWORD, Api, booking_payload


def auto_payload(data, act_idx=0, start=MON, **kw):
    p = booking_payload(data, act_idx=act_idx, start=start, **kw)
    p.pop("resource_id")
    return p


def _locks(bid):
    db = SessionLocal()
    rows = db.scalars(select(BookingResourceLock).where(BookingResourceLock.booking_id == uuid.UUID(bid),
                                                        BookingResourceLock.lock_status.in_(("pending", "confirmed")))).all()
    db.close()
    return rows


# ---------------------------------------------------------------- automatic assignment
def test_booking_without_resource_is_auto_assigned(req1, data):
    r = req1.post("/api/bookings", json=auto_payload(data))
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["resource_display_name"] == "Resource 01" and b["end_date"] == "2027-03-10"
    assert len(_locks(b["id"])) == 8


def test_auto_assign_prefers_earliest_finish_then_lightest_load(admin, req1, req2, data):
    # Resource 01 on leave mid-period -> would finish later, so Resource 02 is chosen
    admin.post("/api/admin/leaves", json={"resource_id": str(data["resources"][0].id), "start_date": "2027-03-03", "end_date": "2027-03-03"})
    assert req1.post("/api/bookings", json=auto_payload(data)).json()["resource_display_name"] == "Resource 02"
    # Resource 02 is now busy; Resource 03 (free, lighter load) is picked over Resource 01 (later finish)
    assert req2.post("/api/bookings", json=auto_payload(data)).json()["resource_display_name"] == "Resource 03"


def test_no_resource_available_suggests_next_date(req1, req2, data):
    for _ in range(3):
        assert req1.post("/api/bookings", json=auto_payload(data)).status_code == 201
    r = req2.post("/api/bookings", json=auto_payload(data))
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_resource_available"
    assert r.json()["error"]["details"]["suggested_start_date"] == "2027-03-11"
    pre = req2.post("/api/availability/auto", json={"activity_type_id": str(data["acts"][0].id), "start_date": "2027-03-01"}).json()
    assert pre["available"] is False and pre["suggested_start_date"] == "2027-03-11"


def test_auto_preview(req1, data):
    pre = req1.post("/api/availability/auto", json={"activity_type_id": str(data["acts"][0].id), "start_date": "2027-03-01"}).json()
    assert pre["available"] is True and pre["resource_display_name"] == "Resource 01"
    assert pre["end_date"] == "2027-03-10" and pre["available_resources"] == 3
    assert "Secret Engineer" not in str(pre)
    wk = req1.post("/api/availability/auto", json={"activity_type_id": str(data["acts"][0].id), "start_date": "2027-03-06"}).json()
    assert wk["available"] is False and wk["reason"] == "non_working_start" and wk["suggested_start_date"] == "2027-03-08"


def test_concurrent_auto_assign_fills_each_resource_once(data):
    n = 6
    barrier = threading.Barrier(n)
    results, lock = [], threading.Lock()

    def worker(i):
        db = SessionLocal()
        try:
            user = db.get(User, data["users"]["req1"].id)
            inp = booking_service.BookingInput(application_name=f"App{i}", application_version="1",
                                               activity_type_id=data["acts"][0].id, pci_dss_scope=False,
                                               start_date=MON, poc_name="P", poc_email="p@example.com")
            barrier.wait()
            b = booking_service.submit_booking(db, user, inp)
            db.commit()
            with lock:
                results.append(str(b.resource_id))
        except ServiceError as e:
            db.rollback()
            with lock:
                results.append(e.code)
        finally:
            db.close()

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assigned = [r for r in results if r not in ("no_resource_available",)]
    assert len(assigned) == 3 and len(set(assigned)) == 3, results
    assert results.count("no_resource_available") == 3


def test_admin_can_reassign_auto_assigned_booking(admin, req1, data):
    b = req1.post("/api/bookings", json=auto_payload(data)).json()
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"resource_id": str(data["resources"][2].id), "reason": "Actual engineer"})
    assert r.status_code == 200 and r.json()["resource_display_name"] == "Resource 03"


# ---------------------------------------------------------------- activities without a resource
def _scan(admin, **kw):
    body = {"name": "XBOW Automated Scan", "requires_resource": False, **kw}
    r = admin.post("/api/admin/activity-types", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_activity_duration_optional_only_without_resource(admin):
    assert admin.post("/api/admin/activity-types", json={"name": "Needs days"}).status_code == 422
    scan = _scan(admin)
    assert scan["base_duration_days"] is None and scan["requires_resource"] is False
    assert admin.patch(f"/api/admin/activity-types/{scan['id']}", json={"requires_resource": True}).status_code == 422


def test_resourceless_booking_without_date(admin, req1, data):
    scan = _scan(admin)
    p = auto_payload(data, application_name="Scan target")
    p.pop("start_date")
    p["activity_type_id"] = scan["id"]
    pre = req1.post("/api/availability/auto", json={"activity_type_id": scan["id"]}).json()
    assert pre["available"] is True and pre["requires_resource"] is False
    r = req1.post("/api/bookings", json=p)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["requires_resource"] is False and b["resource_id"] is None and b["start_date"] is None and b["duration_days"] is None
    assert _locks(b["id"]) == []
    # does not occupy anybody: the calendar stays green
    cal = req1.get("/api/calendar?start=2027-03-01&end=2027-03-01").json()
    assert all(x["days"][0]["state"] == "available" for x in cal["resources"])
    # approve, then mark completed manually
    assert admin.post(f"/api/admin/bookings/{b['id']}/approve").json()["status"] == "approved"
    assert admin.post(f"/api/admin/bookings/{b['id']}/complete", json={"note": "Scan finished"}).json()["status"] == "completed"
    # a resource booking can't be completed manually
    rb = req1.post("/api/bookings", json=auto_payload(data)).json()
    admin.post(f"/api/admin/bookings/{rb['id']}/approve")
    assert admin.post(f"/api/admin/bookings/{rb['id']}/complete").status_code == 409


def test_resourceless_booking_with_date_and_duration(admin, req1, data):
    scan = _scan(admin, base_duration_days=3)
    p = auto_payload(data, start=date(2027, 3, 4))
    p["activity_type_id"] = scan["id"]
    b = req1.post("/api/bookings", json=p).json()
    assert b["start_date"] == "2027-03-04" and b["end_date"] == "2027-03-08" and b["duration_days"] == 3
    p2 = {**p, "resource_id": str(data["resources"][0].id)}
    assert req1.post("/api/bookings", json=p2).status_code == 422  # a resource can't be attached


def test_switching_activity_releases_or_assigns_resource(admin, req1, data):
    scan = _scan(admin)
    b = req1.post("/api/bookings", json=auto_payload(data)).json()
    r = admin.patch(f"/api/admin/bookings/{b['id']}", json={"activity_type_id": scan["id"], "reason": "It's a scan"})
    assert r.status_code == 200 and r.json()["resource_id"] is None and r.json()["requires_resource"] is False
    assert _locks(b["id"]) == []
    back = admin.patch(f"/api/admin/bookings/{b['id']}", json={"activity_type_id": str(data["acts"][0].id), "reason": "Manual PT"})
    assert back.status_code == 200 and back.json()["resource_display_name"] == "Resource 01"
    assert len(_locks(b["id"])) == 8


# ---------------------------------------------------------------- products
def _product(admin, name="Payments", impls=("Bank A", "Bank B")):
    p = admin.post("/api/admin/products", json={"name": name}).json()
    ids = [admin.post(f"/api/admin/products/{p['id']}/implementations", json={"name": n}).json()["id"] for n in impls]
    return p["id"], ids


def test_product_crud_and_validation(admin):
    pid, (i1, _i2) = _product(admin)
    assert admin.post("/api/admin/products", json={"name": "payments"}).status_code == 409
    other, (oi,) = _product(admin, "Loyalty", ("Airline X",))
    bad = admin.post("/api/admin/users", json={"email": "x@test.local", "full_name": "X", "role": "requester",
                                               "password": PASSWORD, "product_id": pid, "implementation_id": oi})
    assert bad.status_code == 422
    ok = admin.post("/api/admin/users", json={"email": "x@test.local", "full_name": "X", "role": "requester",
                                              "password": PASSWORD, "product_id": pid, "implementation_id": i1}).json()
    assert ok["product_name"] == "Payments" and ok["implementation_name"] == "Bank A"
    assert admin.delete(f"/api/admin/products/{pid}").status_code == 409            # in use
    assert admin.patch(f"/api/admin/products/{pid}", json={"is_active": False}).json()["is_active"] is False
    assert admin.delete(f"/api/admin/products/{other}").status_code == 200          # unused


def _assign(admin, data, key, pid, iid):
    r = admin.patch(f"/api/admin/users/{data['users'][key].id}", json={"product_id": pid, "implementation_id": iid})
    assert r.status_code == 200, r.text


def test_bookings_are_tagged_and_shared_within_product(admin, data):
    pid, (i1, i2) = _product(admin)
    _assign(admin, data, "req1", pid, i1)
    _assign(admin, data, "req2", pid, i2)
    r1, r2 = Api("req1@test.local"), Api("req2@test.local")
    b = r1.post("/api/bookings", json=auto_payload(data)).json()
    assert b["product_name"] == "Payments" and b["implementation_name"] == "Bank A"
    # colleague in the same product can see it (read-only)
    mine = r2.get("/api/bookings/mine").json()
    assert mine == []
    team = r2.get("/api/bookings/mine?scope=product").json()
    assert [x["id"] for x in team] == [b["id"]] and team[0]["is_mine"] is False and team[0]["requester_name"] == "Req One"
    assert r2.get(f"/api/bookings/{b['id']}").status_code == 200
    assert r2.get(f"/api/bookings/{b['id']}/history").status_code == 200
    assert r2.post(f"/api/bookings/{b['id']}/cancel", json={"reason": "x"}).status_code == 403
    assert r2.post(f"/api/bookings/{b['id']}/change-requests", json={"request_type": "cancel", "reason": "x"}).status_code == 403
    cell = r2.get("/api/calendar?start=2027-03-01&end=2027-03-01").json()["resources"][0]["days"][0]
    assert cell.get("team") is True and cell["bookings"][0]["id"] == b["id"]
    # a requester outside the product sees nothing
    admin.patch(f"/api/admin/users/{data['users']['req2'].id}", json={"product_id": None})
    assert r2.get(f"/api/bookings/{b['id']}").status_code == 404
    assert r2.get("/api/bookings/mine?scope=product").json() == []


def test_requester_implementation_choice_is_limited_to_own_product(admin, data):
    pid, (i1, i2) = _product(admin)
    _oid, (oi,) = _product(admin, "Loyalty", ("Airline X",))
    _assign(admin, data, "req1", pid, i1)
    r1 = Api("req1@test.local")
    impls = r1.get("/api/me/implementations").json()
    assert impls["product"]["name"] == "Payments" and {i["name"] for i in impls["implementations"]} == {"Bank A", "Bank B"}
    assert r1.post("/api/bookings", json=auto_payload(data, implementation_id=i2)).json()["implementation_name"] == "Bank B"
    assert r1.post("/api/bookings", json=auto_payload(data, implementation_id=oi)).status_code == 422
    assert r1.post("/api/bookings", json={**auto_payload(data), "product_id": _oid}).status_code == 422  # field not accepted


def test_dashboard_product_breakdown_includes_resourceless(admin, data):
    pid, (i1, _) = _product(admin)
    _assign(admin, data, "req1", pid, i1)
    scan = _scan(admin)
    r1 = Api("req1@test.local")
    r1.post("/api/bookings", json=auto_payload(data))
    p = auto_payload(data)
    p.pop("start_date")
    p["activity_type_id"] = scan["id"]
    r1.post("/api/bookings", json=p)
    Api("req2@test.local").post("/api/bookings", json=auto_payload(data, start=date(2027, 4, 5)))
    today = date.today()
    d = admin.get(f"/api/admin/dashboard?start={today.replace(day=1).isoformat()}&end=2027-04-30").json()
    dist = {x["product"]: x for x in d["charts"]["product_distribution"]}
    assert dist["Payments"]["count"] == 2 and dist["Payments"]["without_resource"] == 1
    assert dist["No product"]["count"] == 1
    m = d["charts"]["product_month_matrix"]
    row = next(r for r in m["rows"] if r["product"] == "Payments")
    assert row["total"] == 2 and row["counts"][m["months"].index("2027-03")] == 1
    assert d["kpis"]["bookings_without_resource"] == 1
    assert any(a["activity"] == "XBOW Automated Scan" for a in d["charts"]["activity_distribution"])
    only = admin.get(f"/api/admin/dashboard?start={today.replace(day=1).isoformat()}&end=2027-04-30&product_id={pid}").json()
    assert [x["product"] for x in only["charts"]["product_distribution"]] == ["Payments"]
    csv_text = admin.get("/api/admin/reports/bookings.csv").text
    assert "Product" in csv_text.splitlines()[0] and "Payments" in csv_text and "Not required" in csv_text
