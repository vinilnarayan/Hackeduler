"""Day notes and leave types/limits for the resource dashboard calendar."""
from .conftest import PASSWORD, Api
from .test_resource_calendar import _days, _eng


def _leave(eng, s, e, t, reason=None):
    return eng.post("/api/resource/leaves", json={"start_date": s, "end_date": e, "leave_type": t, "reason": reason})


def test_notes_add_show_edit_delete(admin, data):
    eng = _eng(admin, data)
    r = eng.post("/api/resource/notes", json={"note_date": "2027-03-10", "note": "  Client call at 3pm "})
    assert r.status_code == 201 and r.json()["note"] == "Client call at 3pm"
    nid = r.json()["id"]
    eng.post("/api/resource/notes", json={"note_date": "2027-03-10", "note": "Second"})
    day = _days(eng.get("/api/resource/calendar?month=2027-03").json())["2027-03-10"]
    assert [n["note"] for n in day["notes"]] == ["Client call at 3pm", "Second"]
    assert eng.put(f"/api/resource/notes/{nid}", json={"note": "Moved to 4pm"}).status_code == 200
    assert _days(eng.get("/api/resource/calendar?month=2027-03").json())["2027-03-10"]["notes"][0]["note"] == "Moved to 4pm"
    assert eng.delete(f"/api/resource/notes/{nid}").status_code == 200
    assert len(_days(eng.get("/api/resource/calendar?month=2027-03").json())["2027-03-10"]["notes"]) == 1


def test_notes_are_private_and_validated(admin, data):
    a = _eng(admin, data, 0, "a@test.local")
    b = _eng(admin, data, 1, "b@test.local")
    nid = a.post("/api/resource/notes", json={"note_date": "2027-03-10", "note": "mine"}).json()["id"]
    assert b.put(f"/api/resource/notes/{nid}", json={"note": "x"}).status_code == 404
    assert b.delete(f"/api/resource/notes/{nid}").status_code == 404
    assert all(not d["notes"] for d in b.get("/api/resource/calendar?month=2027-03").json()["days"])
    assert a.post("/api/resource/notes", json={"note_date": "2027-03-10", "note": "   "}).status_code == 422
    assert a.post("/api/resource/notes", json={"note_date": "2027-03-10", "note": "x" * 2001}).status_code == 422
    # a note can be kept on a past day
    assert a.post("/api/resource/notes", json={"note_date": "2020-01-06", "note": "old"}).status_code == 201


def test_notes_are_resource_role_only(admin, data, req1):
    assert req1.post("/api/resource/notes", json={"note_date": "2027-03-10", "note": "x"}).status_code == 403
    assert admin.post("/api/resource/notes", json={"note_date": "2027-03-10", "note": "x"}).status_code == 403


def test_new_leave_types_and_calendar_lists_them(admin, data):
    eng = _eng(admin, data)
    assert _leave(eng, "2027-03-03", "2027-03-03", "Casual leave", "family").status_code == 201
    cal = eng.get("/api/resource/calendar?month=2027-03").json()
    assert "Casual leave" in cal["leave_types"] and "Personal leave" in cal["leave_types"]
    assert _days(cal)["2027-03-03"]["leave"]["leave_type"] == "Casual leave"


def test_personal_leave_limited_to_two_days_per_year(admin, data):
    eng = _eng(admin, data)
    assert _leave(eng, "2027-03-01", "2027-03-02", "Personal leave").status_code == 201      # Mon-Tue = 2 days
    r = _leave(eng, "2027-05-04", "2027-05-04", "Personal leave")
    assert r.status_code == 422 and "limited to 2 days" in r.text
    assert _leave(eng, "2027-05-04", "2027-05-04", "Casual leave").status_code == 201            # other types unaffected
    assert _leave(eng, "2028-01-04", "2028-01-04", "Personal leave").status_code == 201          # new calendar year
    cal = eng.get("/api/resource/calendar?month=2027-03").json()
    assert cal["personal_leave"] == {"year": 2027, "limit": 2, "used": 2}


def test_personal_leave_weekends_dont_count_and_cancel_frees_quota(admin, data):
    eng = _eng(admin, data)
    # Fri 5 Mar - Mon 8 Mar 2027: only two working days (Fri, Mon)
    lid = _leave(eng, "2027-03-05", "2027-03-08", "Personal leave").json()["leave"]["id"]
    assert _leave(eng, "2027-03-10", "2027-03-10", "Personal leave").status_code == 422
    assert eng.delete(f"/api/resource/leaves/{lid}").status_code == 200
    assert _leave(eng, "2027-03-10", "2027-03-10", "Personal leave").status_code == 201


def test_personal_leave_quota_is_per_resource(admin, data):
    a = _eng(admin, data, 0, "a@test.local")
    b = _eng(admin, data, 1, "b@test.local")
    assert _leave(a, "2027-03-01", "2027-03-02", "Personal leave").status_code == 201
    assert _leave(b, "2027-03-01", "2027-03-02", "Personal leave").status_code == 201
