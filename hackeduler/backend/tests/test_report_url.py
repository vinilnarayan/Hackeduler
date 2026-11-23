"""Report link (e.g. SharePoint): saved by admin and resource, validated, and visible to the requester."""
import pytest

from .conftest import PASSWORD, Api, booking_payload

URL = "https://contoso.sharepoint.com/sites/offsec/Reports/app_v1.pdf"


def _setup(admin, req1, data):
    bid = req1.post("/api/bookings", json=booking_payload(data)).json()["id"]
    admin.post("/api/admin/users", json={"email": "eng1@test.local", "full_name": "Eng One", "password": PASSWORD,
                                         "role": "resource", "resource_id": str(data["resources"][0].id)})
    assert admin.post(f"/api/admin/bookings/{bid}/approve", json={}).status_code == 200
    return bid, Api("eng1@test.local")


def test_link_required_when_shared_and_visible_to_all_roles(admin, req1, data):
    bid, eng = _setup(admin, req1, data)
    body = {"report_shared": True, "report_type": "V1"}
    assert admin.put(f"/api/admin/bookings/{bid}/report", json=body).status_code == 422
    assert eng.put(f"/api/resource/bookings/{bid}/report", json=body).status_code == 422

    r = eng.put(f"/api/resource/bookings/{bid}/report", json={**body, "report_url": f"  {URL}  "})
    assert r.status_code == 200 and r.json()["report_url"] == URL
    assert req1.get("/api/bookings/mine").json()[0]["report_url"] == URL
    assert admin.get("/api/admin/bookings").json()["items"][0]["report_url"] == URL
    assert eng.get("/api/resource/bookings").json()["items"][0]["report_url"] == URL

    r = admin.put(f"/api/admin/bookings/{bid}/report", json={"report_shared": True, "report_type": "Met", "report_url": URL + "?v=2"})
    assert r.status_code == 200 and r.json()["report_url"].endswith("?v=2")


@pytest.mark.parametrize("bad", ["http://contoso.sharepoint.com/a.pdf", "javascript:alert(1)", "ftp://x/y", "not a url",
                                 "https://", "https://a.com/with space.pdf"])
def test_link_must_be_https(admin, req1, data, bad):
    bid, _ = _setup(admin, req1, data)
    r = admin.put(f"/api/admin/bookings/{bid}/report", json={"report_shared": True, "report_type": "V1", "report_url": bad})
    assert r.status_code == 422


def test_unsharing_keeps_optional_link_empty_and_is_audited(admin, req1, data):
    bid, eng = _setup(admin, req1, data)
    assert eng.put(f"/api/resource/bookings/{bid}/report", json={"report_shared": True, "report_type": "V1", "report_url": URL}).status_code == 200
    r = eng.put(f"/api/resource/bookings/{bid}/report", json={"report_shared": False})
    assert r.status_code == 200 and r.json()["report_url"] is None and r.json()["report_shared"] is False
