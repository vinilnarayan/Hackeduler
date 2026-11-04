"""Concurrent booking prevention (criteria 7-9)."""
import threading
import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.errors import ServiceError
from app.models import Booking, BookingResourceLock, User
from app.services import booking_service

from .conftest import MON


def _inp(data, start=MON, resource_idx=0):
    return booking_service.BookingInput(
        application_name="App", application_version="1", activity_type_id=data["acts"][0].id, pci_dss_scope=False,
        resource_id=data["resources"][resource_idx].id, start_date=start, poc_name="P", poc_email="p@example.com")


@pytest.mark.parametrize("n", [8])
def test_only_one_of_many_simultaneous_requests_succeeds(data, n):
    barrier = threading.Barrier(n)
    results = []
    lock = threading.Lock()
    starts = [MON, date(2027, 3, 2), date(2027, 3, 3), date(2027, 3, 4)] * 2  # all overlap with each other

    def worker(i):
        db = SessionLocal()
        try:
            user = db.get(User, data["users"]["req1" if i % 2 else "req2"].id)
            barrier.wait()
            booking_service.submit_booking(db, user, _inp(data, start=starts[i]))
            db.commit()
            with lock:
                results.append("ok")
        except ServiceError as e:
            db.rollback()
            with lock:
                results.append(e.code)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1, results
    assert all(r == "resource_unavailable" for r in results if r != "ok")
    db = SessionLocal()
    assert db.query(Booking).count() == 1
    db.close()


def test_http_level_concurrency(data):
    from fastapi.testclient import TestClient

    from app.main import app

    from .conftest import PASSWORD, booking_payload

    clients = []
    for email in ("req1@test.local", "req2@test.local") * 3:
        c = TestClient(app)
        csrf = c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["csrf_token"]
        clients.append((c, csrf))
    barrier = threading.Barrier(len(clients))
    codes = []

    def go(c, csrf):
        barrier.wait()
        r = c.post("/api/bookings", json=booking_payload(data), headers={"X-CSRF-Token": csrf})
        codes.append((r.status_code, r.json().get("error", {}).get("message")))

    ts = [threading.Thread(target=go, args=cc) for cc in clients]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(c for c, _ in codes) == [201] + [409] * (len(clients) - 1)
    msgs = {m for c, m in codes if c == 409}
    assert msgs == {"The selected resource is no longer available for the requested dates. Please select another resource or date."}


def test_database_unique_index_is_last_line_of_defence(data):
    """Even bypassing the service layer, PostgreSQL rejects two active non-forced locks on one resource-day."""
    db = SessionLocal()
    b = booking_service.submit_booking(db, db.get(User, data["users"]["req1"].id), _inp(data))
    db.commit()
    db.add(BookingResourceLock(id=uuid.uuid4(), booking_id=b.id, resource_id=b.resource_id, work_date=MON,
                               lock_status="pending", is_forced=False))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


def test_different_resources_in_parallel_all_succeed(data):
    barrier = threading.Barrier(3)
    ok = []

    def worker(i):
        db = SessionLocal()
        try:
            barrier.wait()
            booking_service.submit_booking(db, db.get(User, data["users"]["req1"].id), _inp(data, resource_idx=i))
            db.commit()
            ok.append(i)
        finally:
            db.close()

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(ok) == [0, 1, 2]
