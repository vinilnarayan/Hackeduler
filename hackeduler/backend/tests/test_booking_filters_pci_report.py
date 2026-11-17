"""Admin bookings list and exports: PCI and report filters."""
from .conftest import booking_payload


def _setup(admin, data):
    ids = {}
    for key, idx, pci in (("a", 0, True), ("b", 1, False), ("c", 2, True)):
        r = admin.post("/api/admin/bookings", json=booking_payload(data, idx, pci_dss_scope=pci, application_name=f"App {key}"))
        assert r.status_code == 201, r.text
        ids[key] = r.json()["id"]
    assert admin.put(f"/api/admin/bookings/{ids['a']}/report", json={"report_shared": True, "report_type": "V1"}).status_code == 200
    assert admin.put(f"/api/admin/bookings/{ids['b']}/report", json={"report_shared": True, "report_type": "Met"}).status_code == 200
    return ids


def _names(admin, **params):
    r = admin.get("/api/admin/bookings", params=params)
    assert r.status_code == 200, r.text
    return {i["application_name"] for i in r.json()["items"]}


def test_pci_filter(admin, data):
    _setup(admin, data)
    assert _names(admin, pci="true") == {"App a", "App c"}
    assert _names(admin, pci="false") == {"App b"}


def test_report_filters(admin, data):
    _setup(admin, data)
    assert _names(admin, report_shared="true") == {"App a", "App b"}
    assert _names(admin, report_shared="false") == {"App c"}
    assert _names(admin, report_shared="true", report_type="V1") == {"App a"}
    assert _names(admin, report_type="Met") == {"App b"}
    assert _names(admin, pci="true", report_shared="true") == {"App a"}
    assert admin.get("/api/admin/bookings", params={"report_type": "Bogus"}).status_code == 422


def test_exports_follow_the_filters(admin, data):
    _setup(admin, data)
    csv = admin.get("/api/admin/reports/bookings.csv", params={"pci": "true", "report_shared": "true"}).text
    assert "App a" in csv and "App b" not in csv and "App c" not in csv
