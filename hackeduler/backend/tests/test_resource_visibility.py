"""Resources hidden from requesters: admin-only assignment."""
from datetime import date

from .conftest import booking_payload

START, END = "2027-03-01", "2027-03-31"


def _hide(admin, res):
    r = admin.patch(f"/api/admin/resources/{res.id}", json={"visible_to_requesters": False})
    assert r.status_code == 200 and r.json()["visible_to_requesters"] is False


def _calendar_ids(client):
    return {r["id"] for r in client.get(f"/api/calendar?start={START}&end={END}").json()["resources"]}


def test_new_resources_are_visible_by_default(admin):
    r = admin.post("/api/admin/resources", json={"engineer_name": "New Eng"})
    assert r.status_code == 201 and r.json()["visible_to_requesters"] is True


def test_resource_can_be_created_hidden(admin, req1):
    r = admin.post("/api/admin/resources", json={"engineer_name": "Hidden Eng", "visible_to_requesters": False})
    assert r.status_code == 201 and r.json()["visible_to_requesters"] is False
    assert r.json()["id"] not in {x["id"] for x in req1.get("/api/resources").json()}
    assert r.json()["id"] in {x["id"] for x in admin.get("/api/admin/resources").json()}


def test_hidden_resource_not_in_requester_lists_or_calendar_but_in_admin_calendar(admin, req1, data):
    hidden = data["resources"][2]
    _hide(admin, hidden)
    assert str(hidden.id) not in {x["id"] for x in req1.get("/api/resources").json()}
    assert str(hidden.id) not in _calendar_ids(req1)
    assert str(hidden.id) in {r["id"] for r in admin.get(f"/api/admin/calendar?start={START}&end={END}").json()["resources"]}


def test_requester_cannot_choose_or_check_a_hidden_resource(admin, req1, data):
    hidden = data["resources"][0]
    _hide(admin, hidden)
    assert req1.post("/api/bookings", json=booking_payload(data)).status_code == 404
    chk = req1.post("/api/availability/check", json={"resource_id": str(hidden.id), "activity_type_id": str(data["acts"][0].id), "start_date": START})
    assert chk.status_code == 404


def test_hidden_resource_is_never_auto_assigned(admin, req1, data):
    for r in data["resources"][:2]:
        _hide(admin, r)
    p = booking_payload(data)
    p.pop("resource_id", None)
    r = req1.post("/api/bookings", json=p)
    assert r.status_code == 201 and r.json()["resource_display_name"] == data["resources"][2].display_name
    _hide(admin, data["resources"][2])
    p["application_name"] = "Another"
    assert req1.post("/api/bookings", json=p).status_code == 409           # nothing visible is left


def test_admin_can_still_assign_a_hidden_resource(admin, data):
    _hide(admin, data["resources"][0])
    r = admin.post("/api/admin/bookings", json=booking_payload(data))
    assert r.status_code == 201 and r.json()["status"] == "approved"
    # ...and it is then busy for the admin check
    chk = admin.post("/api/admin/availability/check", json={"resource_id": str(data["resources"][0].id), "activity_type_id": str(data["acts"][0].id), "start_date": START})
    assert chk.json()["available"] is False


def test_requester_dashboard_does_not_count_hidden(admin, req1, data):
    before = req1.get("/api/me/dashboard").json()["active_resources"]
    _hide(admin, data["resources"][0])
    assert req1.get("/api/me/dashboard").json()["active_resources"] == before - 1


def test_only_admins_can_change_visibility(req1, data):
    assert req1.patch(f"/api/admin/resources/{data['resources'][0].id}", json={"visible_to_requesters": False}).status_code == 403
