"""Activity types: optional yearly booking limit (balance shown to requesters, counted on admin acceptance)."""
from .conftest import booking_payload


def _scan(admin, limit=2, **kw):
    r = admin.post("/api/admin/activity-types", json={"name": "XBOW Quota", "requires_resource": False, "yearly_limit": limit, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _payload(data, scan, start=None, **kw):
    p = booking_payload(data, **kw)
    p.pop("resource_id", None)
    p["activity_type_id"] = scan["id"]
    if start:
        p["start_date"] = start
    else:
        p.pop("start_date", None)
    return p


def _quota(req, scan, start=None):
    body = {"activity_type_id": scan["id"], **({"start_date": start} if start else {})}
    return req.post("/api/availability/auto", json=body).json()


def test_unlimited_by_default(admin, req1, data):
    a = admin.post("/api/admin/activity-types", json={"name": "Free", "requires_resource": False}).json()
    assert a["yearly_limit"] is None
    listed = {x["name"]: x for x in req1.get("/api/activity-types").json()}
    assert listed["Free"]["quota"] is None
    assert _quota(req1, a)["quota"] is None


def test_balance_counts_down_when_admin_accepts(admin, req1, data):
    scan = _scan(admin, 10)
    assert _quota(req1, scan, "2027-03-01")["quota"] == {"year": 2027, "limit": 10, "used": 0, "remaining": 10}
    b = req1.post("/api/bookings", json=_payload(data, scan, "2027-03-01")).json()
    assert _quota(req1, scan, "2027-03-01")["quota"]["remaining"] == 10      # pending requests do not use the balance yet
    assert admin.post(f"/api/admin/bookings/{b['id']}/approve").status_code == 200
    q = _quota(req1, scan, "2027-03-01")["quota"]
    assert q["used"] == 1 and q["remaining"] == 9
    assert _quota(req1, scan, "2028-03-01")["quota"]["remaining"] == 10      # other years are independent


def test_full_year_blocks_submit_and_approval(admin, req1, data):
    scan = _scan(admin, 1)
    first = req1.post("/api/bookings", json=_payload(data, scan, "2027-03-01")).json()
    second = req1.post("/api/bookings", json=_payload(data, scan, "2027-04-01")).json()
    assert admin.post(f"/api/admin/bookings/{first['id']}/approve").status_code == 200
    pre = _quota(req1, scan, "2027-05-03")
    assert pre["available"] is False and pre["reason"] == "yearly_limit_reached"
    r = req1.post("/api/bookings", json=_payload(data, scan, "2027-05-03"))
    assert r.status_code == 409 and "yearly_limit_reached" in r.text
    r = admin.post(f"/api/admin/bookings/{second['id']}/approve")
    assert r.status_code == 409
    # next year is still open; raising the limit reopens this year
    assert req1.post("/api/bookings", json=_payload(data, scan, "2028-03-01")).status_code == 201
    assert admin.patch(f"/api/admin/activity-types/{scan['id']}", json={"yearly_limit": 2}).status_code == 200
    assert admin.post(f"/api/admin/bookings/{second['id']}/approve").status_code == 200


def test_limit_validation_and_listing(admin, req1, data):
    assert admin.post("/api/admin/activity-types", json={"name": "Bad", "requires_resource": False, "yearly_limit": 0}).status_code == 422
    scan = _scan(admin, 5)
    listed = {x["name"]: x for x in req1.get("/api/activity-types").json()}
    assert listed["XBOW Quota"]["yearly_limit"] == 5 and listed["XBOW Quota"]["quota"]["remaining"] == 5
    assert {x["name"]: x for x in admin.get("/api/admin/activity-types").json()}["XBOW Quota"]["yearly_limit"] == 5


def test_applies_to_resource_activities_too(admin, req1, data):
    act = data["acts"][0]
    assert admin.patch(f"/api/admin/activity-types/{act.id}", json={"yearly_limit": 1}).status_code == 200
    b = req1.post("/api/bookings", json=booking_payload(data)).json()
    assert admin.post(f"/api/admin/bookings/{b['id']}/approve").status_code == 200
    r = req1.post("/api/bookings", json=booking_payload(data))
    assert r.status_code == 409 and "yearly_limit_reached" in r.text
