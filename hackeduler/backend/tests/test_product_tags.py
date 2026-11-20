"""Tags on products and implementations, and the admin dashboard tag filter."""
from .conftest import MON, PASSWORD, Api, booking_payload


def _prod(admin, name, **kw):
    r = admin.post("/api/admin/products", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _user(admin, email, product_id, impl=None):
    r = admin.post("/api/admin/users", json={"email": email, "full_name": "T", "password": PASSWORD, "role": "requester",
                                             "product_id": product_id, **({"implementation_id": impl} if impl else {})})
    assert r.status_code == 201, r.text
    return Api(email)


def test_tags_are_cleaned_saved_and_listed(admin):
    p = _prod(admin, "Alpha", tags=["  Payments ", "payments", "Core  Banking", ""])
    assert p["tags"] == ["Payments", "Core Banking"]               # trimmed, spaces collapsed, case-insensitive de-dupe
    i = admin.post(f"/api/admin/products/{p['id']}/implementations", json={"name": "Cloud", "tags": ["SaaS", "EU"]}).json()
    assert i["tags"] == ["SaaS", "EU"]
    r = admin.patch(f"/api/admin/products/{p['id']}", json={"tags": ["Cards"]})
    assert r.json()["tags"] == ["Cards"]
    assert admin.patch(f"/api/admin/products/{p['id']}", json={"description": "x"}).json()["tags"] == ["Cards"]   # untouched
    assert admin.patch(f"/api/admin/implementations/{i['id']}", json={"tags": []}).json()["tags"] == []
    listed = {x["name"]: x for x in admin.get("/api/admin/products").json()}
    assert listed["Alpha"]["tags"] == ["Cards"] and listed["Alpha"]["implementations"][0]["tags"] == []
    assert admin.post("/api/admin/products", json={"name": "Long", "tags": ["x" * 41]}).status_code == 422
    assert admin.post("/api/admin/products", json={"name": "Many", "tags": [f"t{n}" for n in range(21)]}).status_code == 422
    assert _prod(admin, "Plain")["tags"] == []


def test_dashboard_tag_filter(admin, data):
    a = _prod(admin, "Alpha", tags=["Payments"])
    b = _prod(admin, "Beta", tags=["Other"])
    impl = admin.post(f"/api/admin/products/{b['id']}/implementations", json={"name": "Special", "tags": ["PAYMENTS"]}).json()
    ra, rb, rc = _user(admin, "a@test.local", a["id"]), _user(admin, "b@test.local", b["id"], impl["id"]), _user(admin, "c@test.local", b["id"])
    for n, api in enumerate((ra, rb, rc)):
        assert api.post("/api/bookings", json=booking_payload(data, n, start=MON)).status_code == 201

    def total(**q):
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return admin.get(f"/api/admin/dashboard?{qs}").json()["kpis"]["bookings_in_range"]

    assert total() == 3
    assert total(tag="Payments") == 2                    # Alpha via its product tag, Beta/Special via the implementation tag
    assert total(tag="payments") == 2                    # case-insensitive
    assert total(tag="Other") == 2                       # both Beta bookings, via the product tag
    assert total(tag="Nope") == 0
    assert total(tag="Payments", product_id=a["id"]) == 1  # combines with the product filter


def test_export_follows_tag_filter(admin, data):
    a = _prod(admin, "Alpha", tags=["Payments"])
    b = _prod(admin, "Beta")
    for n, (prod, email) in enumerate(((a, "a@test.local"), (b, "b@test.local"))):
        assert _user(admin, email, prod["id"]).post("/api/bookings", json=booking_payload(data, n, start=MON)).status_code == 201
    full = admin.get("/api/admin/reports/bookings.csv").text.strip().splitlines()
    only = admin.get("/api/admin/reports/bookings.csv?tag=payments").text.strip().splitlines()
    assert len(full) == 3 and len(only) == 2
