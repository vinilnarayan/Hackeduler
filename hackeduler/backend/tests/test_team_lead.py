"""Resource users marked as team leads get a read-only Team Calendar; everyone else does not."""
from .conftest import MON, PASSWORD, Api, booking_payload


def _eng(admin, resource, email, **kw):
    r = admin.post("/api/admin/users", json={"email": email, "full_name": email.split("@")[0], "password": PASSWORD,
                                             "role": "resource", "resource_id": str(resource.id), **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_lead_flag_is_set_listed_and_exposed_on_me(admin, data):
    lead = _eng(admin, data["resources"][0], "lead@test.local", is_lead=True)
    plain = _eng(admin, data["resources"][1], "plain@test.local")
    assert lead["is_lead"] is True and plain["is_lead"] is False
    assert Api("lead@test.local").get("/api/auth/me").json()["user"]["is_lead"] is True
    assert Api("plain@test.local").get("/api/auth/me").json()["user"]["is_lead"] is False
    listed = {u["email"]: u for u in admin.get("/api/admin/users").json()}
    assert listed["lead@test.local"]["is_lead"] is True and listed["plain@test.local"]["is_lead"] is False


def test_only_resource_users_can_be_leads(admin, data):
    r = admin.post("/api/admin/users", json={"email": "r@test.local", "full_name": "R", "password": PASSWORD, "role": "requester", "is_lead": True})
    assert r.status_code == 422
    u = _eng(admin, data["resources"][0], "e@test.local")
    assert admin.patch(f"/api/admin/users/{u['id']}", json={"is_lead": True}).json()["is_lead"] is True
    assert admin.patch(f"/api/admin/users/{u['id']}", json={"is_lead": False}).json()["is_lead"] is False
    assert admin.patch(f"/api/admin/users/{u['id']}", json={"is_lead": True}).status_code == 200
    back = admin.patch(f"/api/admin/users/{u['id']}", json={"role": "requester"})          # leaving the resource role drops the flag
    assert back.status_code == 200 and back.json()["is_lead"] is False
    assert admin.patch(f"/api/admin/users/{u['id']}", json={"is_lead": True}).status_code == 422


def test_lead_sees_the_team_calendar_others_do_not(admin, req1, data):
    admin.post("/api/admin/bookings", json=booking_payload(data, 1, start=MON, duration_days=2))
    _eng(admin, data["resources"][0], "lead@test.local", is_lead=True)
    _eng(admin, data["resources"][2], "plain@test.local")
    lead, plain = Api("lead@test.local"), Api("plain@test.local")
    cal = lead.get("/api/resource/team-calendar?month=2027-03").json()
    assert cal["month"] == "2027-03" and len(cal["resources"]) == 3
    assert any(d["entries"] for d in cal["days"])                                   # another engineer's booking is visible
    wk = lead.get("/api/resource/team-calendar?week=2027-03-03").json()
    assert [d["date"] for d in wk["days"]][0] == "2027-03-01" and len(wk["days"]) == 7
    one = lead.get(f"/api/resource/team-calendar?month=2027-03&resource_id={data['resources'][1].id}").json()
    assert any(d["entries"] for d in one["days"])
    assert plain.get("/api/resource/team-calendar").status_code == 403
    assert req1.get("/api/resource/team-calendar").status_code == 403
    assert admin.get("/api/resource/team-calendar").status_code == 403               # admins use their own page
    # a lead is still read-only and still limited to their own assignments elsewhere
    assert lead.get("/api/admin/team-calendar").status_code == 403
    assert lead.get("/api/admin/users").status_code == 403


def test_demoting_a_lead_removes_access_immediately(admin, data):
    u = _eng(admin, data["resources"][0], "lead@test.local", is_lead=True)
    lead = Api("lead@test.local")
    assert lead.get("/api/resource/team-calendar").status_code == 200
    admin.patch(f"/api/admin/users/{u['id']}", json={"is_lead": False})
    assert lead.get("/api/resource/team-calendar").status_code == 403


def test_resource_calendar_week_parameter(admin, data):
    _eng(admin, data["resources"][0], "eng@test.local")
    eng = Api("eng@test.local")
    cal = eng.get("/api/resource/calendar?week=2027-03-03").json()
    assert cal["week"] == "2027-03-01" and [d["date"] for d in cal["days"]] == [f"2027-03-0{n}" for n in range(1, 8)]
    assert all(d["in_month"] for d in cal["days"])
    assert eng.get("/api/resource/calendar?month=2027-03").json()["week"] is None
    assert eng.get("/api/resource/calendar?week=1999-01-01").status_code == 422
