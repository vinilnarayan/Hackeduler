"""Admin bookings list and exports: PCI and report filters."""
from .conftest import booking_payload


def _setup(admin, data):
    ids = {}
    for key, idx, pci in (("a", 0, True), ("b", 1, False), ("c", 2, True)):
        r = admin.post("/api/admin/bookings", json=booking_payload(data, idx, pci_dss_scope=pci, application_name=f"App {key}"))
        assert r.status_code == 201, r.text
        ids[key] = r.json()["id"]
    assert admin.put(f"/api/admin/bookings/{ids['a']}/report", json={"report_shared": True, "report_type": "V1", "report_url": "https://contoso.sharepoint.com/r.pdf"}).status_code == 200
    assert admin.put(f"/api/admin/bookings/{ids['b']}/report", json={"report_shared": True, "report_type": "Met", "report_url": "https://contoso.sharepoint.com/r.pdf"}).status_code == 200
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


def test_list_summary_counts_follow_the_filters(admin, data):
    _setup(admin, data)
    s = admin.get("/api/admin/bookings").json()["summary"]
    assert s == {"total": 3, "pci": 2, "non_pci": 1, "report_shared": 2, "report_not_shared": 1}
    s = admin.get("/api/admin/bookings", params={"pci": "true"}).json()["summary"]
    assert s == {"total": 2, "pci": 2, "non_pci": 0, "report_shared": 1, "report_not_shared": 1}
    s = admin.get("/api/admin/bookings", params={"report_shared": "true", "limit": 1}).json()
    assert len(s["items"]) == 1 and s["total"] == 2 and s["summary"]["total"] == 2 and s["summary"]["pci"] == 1   # not just the page


def test_dashboard_pci_and_report_counts_follow_the_filters(admin, data):
    _setup(admin, data)
    k = admin.get("/api/admin/dashboard", params={"start": "2027-01-01", "end": "2027-12-31"}).json()["kpis"]
    assert (k["pci_bookings"], k["non_pci_bookings"], k["reports_shared"]) == (2, 1, 2)
    k = admin.get("/api/admin/dashboard", params={"start": "2028-01-01", "end": "2028-12-31"}).json()["kpis"]
    assert (k["pci_bookings"], k["non_pci_bookings"], k["reports_shared"]) == (0, 0, 0)
    pid = admin.get("/api/admin/products").json()
    if pid:
        k = admin.get("/api/admin/dashboard", params={"start": "2027-01-01", "end": "2027-12-31", "product_id": pid[0]["id"]}).json()["kpis"]
        assert k["pci_bookings"] + k["non_pci_bookings"] == k["bookings_in_range"]


def test_list_sorting_is_applied_before_paging(admin, data):
    _setup(admin, data)

    def order(**p):
        r = admin.get("/api/admin/bookings", params=p)
        assert r.status_code == 200, r.text
        return [i["application_name"] for i in r.json()["items"]]
    assert order(sort_by="application", sort_dir="asc") == ["App a", "App b", "App c"]
    assert order(sort_by="application", sort_dir="desc") == ["App c", "App b", "App a"]
    assert order(sort_by="application", sort_dir="desc", limit=1) == ["App c"]              # whole set ordered, then paged
    assert order(sort_by="application", sort_dir="asc", limit=1, offset=2) == ["App c"]
    assert order(sort_by="pci", sort_dir="asc")[0] == "App b"                                # False before True
    assert order(sort_by="report", sort_dir="asc")[:2] == ["App b", "App a"]                  # Met < V1, unshared last
    for col in ("id", "version", "activity", "dates", "poc", "submitted", "status", "product", "resource", "requester"):
        assert len(order(sort_by=col)) == 3
    assert admin.get("/api/admin/bookings", params={"sort_by": "password"}).status_code == 422
    assert admin.get("/api/admin/bookings", params={"sort_dir": "sideways"}).status_code == 422
