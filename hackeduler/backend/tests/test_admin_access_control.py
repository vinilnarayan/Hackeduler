"""Every admin endpoint must refuse requesters (403) and anonymous callers (401)."""
import re
import uuid

from app.main import app

SAMPLE = {"uuid": str(uuid.uuid4())}


def _admin_routes():
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api/admin"):
            for m in ops:
                if m.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    yield m.upper(), re.sub(r"\{[^}]+\}", SAMPLE["uuid"], path)


def test_there_are_admin_routes():
    assert len(list(_admin_routes())) > 40


def test_requesters_are_refused_everywhere(req1):
    leaks = []
    for method, path in _admin_routes():
        r = req1.c.request(method, path, json={} if method in ("POST", "PUT", "PATCH", "DELETE") else None, headers={"X-CSRF-Token": req1.csrf})
        if r.status_code != 403:
            leaks.append((method, path, r.status_code))
    assert not leaks, leaks


def test_anonymous_callers_are_refused_everywhere(data):
    from fastapi.testclient import TestClient

    anon = TestClient(app)
    leaks = []
    for method, path in _admin_routes():
        r = anon.request(method, path, json={} if method in ("POST", "PUT", "PATCH", "DELETE") else None)
        if r.status_code not in (401, 403):
            leaks.append((method, path, r.status_code))
    assert not leaks, leaks
