"""Requesters who belong to several products."""
from datetime import date

from .conftest import MON, PASSWORD, Api, booking_payload


def _prod(admin, name):
    r = admin.post("/api/admin/products", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _impl(admin, product, name):
    r = admin.post(f"/api/admin/products/{product['id']}/implementations", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _user(admin, email, **kw):
    r = admin.post("/api/admin/users", json={"email": email, "full_name": email.split("@")[0], "password": PASSWORD, "role": "requester", **kw})
    assert r.status_code == 201, r.text
    return r.json(), Api(email)


def _book(api, data, res=0, start=MON, **kw):
    return api.post("/api/bookings", json=booking_payload(data, res, start=start, **kw))


def test_admin_sets_and_changes_additional_products(admin, data):
    a, b, c = _prod(admin, "Alpha"), _prod(admin, "Beta"), _prod(admin, "Gamma")
    u, _ = _user(admin, "multi@test.local", product_id=a["id"], extra_product_ids=[b["id"], c["id"], a["id"]])
    assert [p["name"] for p in u["products"]] == ["Alpha", "Beta", "Gamma"]       # primary first, duplicate of primary ignored
    assert sorted(u["extra_product_ids"]) == sorted([b["id"], c["id"]])
    r = admin.patch(f"/api/admin/users/{u['id']}", json={"extra_product_ids": [c["id"]]})
    assert [p["name"] for p in r.json()["products"]] == ["Alpha", "Gamma"]
    # moving the primary to one that was additional drops the duplicate
    r = admin.patch(f"/api/admin/users/{u['id']}", json={"product_id": c["id"]})
    assert r.status_code == 200 and [p["name"] for p in r.json()["products"]] == ["Gamma"]
    # clearing the primary clears the rest
    admin.patch(f"/api/admin/users/{u['id']}", json={"extra_product_ids": [a["id"]]})
    r = admin.patch(f"/api/admin/users/{u['id']}", json={"product_id": None})
    assert r.json()["products"] == []


def test_additional_products_need_a_primary_and_must_exist(admin, data):
    a = _prod(admin, "Alpha")
    r = admin.post("/api/admin/users", json={"email": "x@test.local", "full_name": "X", "password": PASSWORD, "role": "requester",
                                             "extra_product_ids": [a["id"]]})
    assert r.status_code == 422
    r = admin.post("/api/admin/users", json={"email": "y@test.local", "full_name": "Y", "password": PASSWORD, "role": "requester",
                                             "product_id": a["id"], "extra_product_ids": ["00000000-0000-0000-0000-000000000001"]})
    assert r.status_code == 422


def test_requester_can_book_under_any_of_their_products(admin, data):
    a, b = _prod(admin, "Alpha"), _prod(admin, "Beta")
    ia, ib = _impl(admin, a, "A-impl"), _impl(admin, b, "B-impl")
    _, me = _user(admin, "multi@test.local", product_id=a["id"], implementation_id=ia["id"], extra_product_ids=[b["id"]])
    opts = me.get("/api/me/implementations").json()
    assert opts["product"]["name"] == "Alpha" and opts["default_implementation_id"] == ia["id"]       # old shape unchanged
    assert [(p["name"], p["is_primary"]) for p in opts["products"]] == [("Alpha", True), ("Beta", False)]
    assert opts["products"][1]["implementations"][0]["id"] == ib["id"]

    r = _book(me, data, product_id=b["id"], implementation_id=ib["id"])
    assert r.status_code == 201 and r.json()["product_name"] == "Beta" and r.json()["implementation_name"] == "B-impl"
    r2 = _book(me, data, res=1)                                                                         # default: primary + its implementation
    assert r2.status_code == 201 and r2.json()["product_name"] == "Alpha" and r2.json()["implementation_name"] == "A-impl"
    # an implementation of another of my products selects that product by itself
    r3 = me.post("/api/bookings", json={**booking_payload(data, 2, start=MON), "implementation_id": ib["id"]})
    assert r3.status_code == 201 and r3.json()["product_name"] == "Beta"
    # a mismatched pair is still rejected
    r4 = _book(me, data, res=1, start=date(2027, 4, 5), product_id=b["id"], implementation_id=ia["id"])
    assert r4.status_code == 422


def test_cannot_book_under_a_product_that_is_not_theirs(admin, data):
    a, b = _prod(admin, "Alpha"), _prod(admin, "Beta")
    _, me = _user(admin, "one@test.local", product_id=a["id"])
    assert _book(me, data, product_id=b["id"]).status_code == 403


def test_bookings_of_all_my_products_are_visible_but_not_changeable(admin, data):
    a, b, c = _prod(admin, "Alpha"), _prod(admin, "Beta"), _prod(admin, "Gamma")
    _, in_a = _user(admin, "a@test.local", product_id=a["id"])
    _, in_b = _user(admin, "b@test.local", product_id=b["id"])
    _, in_c = _user(admin, "c@test.local", product_id=c["id"])
    _, multi = _user(admin, "multi@test.local", product_id=a["id"], extra_product_ids=[b["id"]])
    ba, bb, bc = (_book(u, data, res=i).json() for i, u in enumerate((in_a, in_b, in_c)))
    seen = {x["id"] for x in multi.get("/api/bookings/mine?scope=product").json()}
    assert ba["id"] in seen and bb["id"] in seen and bc["id"] not in seen
    assert multi.get(f"/api/bookings/{bb['id']}").status_code == 200
    assert multi.get(f"/api/bookings/{bc['id']}").status_code == 404
    assert multi.post(f"/api/bookings/{bb['id']}/cancel", json={"reason": "x"}).status_code == 403      # colleagues' bookings are read-only
    # product colleagues of the extra product do not gain access to the multi user's other products
    assert in_b.get(f"/api/bookings/{ba['id']}").status_code == 404


def test_product_user_counts_include_additional_members_and_block_delete(admin, data):
    a, b = _prod(admin, "Alpha"), _prod(admin, "Beta")
    _user(admin, "multi@test.local", product_id=a["id"], extra_product_ids=[b["id"]])
    prods = {p["name"]: p for p in admin.get("/api/admin/products").json()}
    assert prods["Alpha"]["users"] == 1 and prods["Beta"]["users"] == 1
    assert admin.delete(f"/api/admin/products/{b['id']}").status_code == 409


def test_existing_single_product_users_are_unchanged(admin, data):
    a = _prod(admin, "Alpha")
    u, me = _user(admin, "solo@test.local", product_id=a["id"])
    assert u["extra_product_ids"] == [] and [p["name"] for p in u["products"]] == ["Alpha"]
    assert me.get("/api/auth/me").json()["user"]["products"][0]["name"] == "Alpha"
