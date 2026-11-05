"""Test fixtures. Tests run against a REAL PostgreSQL database (default: hackeduler_test)
because the locking guarantees rely on PostgreSQL row locks and partial unique indexes.

    HACKEDULER_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/hackeduler_test pytest
"""
from __future__ import annotations

import os
import uuid
from datetime import date

os.environ["HACKEDULER_DATABASE_URL"] = os.environ.get(
    "HACKEDULER_TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/hackeduler_test")
os.environ["HACKEDULER_ENVIRONMENT"] = "test"
os.environ["HACKEDULER_EMAIL_BACKEND"] = "memory"
os.environ["HACKEDULER_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["HACKEDULER_LOGIN_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["HACKEDULER_SECRET_KEY"] = "test-secret-key-for-unit-tests-only-0123456789"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import ROLE_ADMIN_ID, ROLE_REQUESTER_ID, ActivityType, SecurityResource, User  # noqa: E402
from app.security import hash_password, limiter  # noqa: E402
from app.services import email_sender  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSWORD = "Str0ng!Password"
MON = date(2027, 3, 1)  # a Monday comfortably in the future
TABLES = ("application_settings, email_notification_logs, email_templates, booking_conflicts, audit_logs, "
          "booking_change_requests, booking_resource_locks, booking_status_history, bookings, resource_leaves, "
          "holidays, activity_types, security_resources, users, sso_providers, implementations, products")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    command.upgrade(cfg, "head")
    yield


_HASH = hash_password(PASSWORD)


@pytest.fixture(autouse=True)
def clean_db():
    # session_replication_role=replica bypasses the append-only triggers for TEST CLEANUP ONLY
    # (requires superuser; the application role in production must not be a superuser).
    with engine.begin() as c:
        c.execute(text("SET session_replication_role = replica"))
        c.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        c.execute(text("SET session_replication_role = DEFAULT"))
    email_sender.SENT_MESSAGES.clear()
    limiter.reset()
    db = SessionLocal()
    users = {
        "admin": User(id=uuid.uuid4(), email="admin@test.local", full_name="Admin", password_hash=_HASH, role_id=ROLE_ADMIN_ID),
        "req1": User(id=uuid.uuid4(), email="req1@test.local", full_name="Req One", password_hash=_HASH, role_id=ROLE_REQUESTER_ID),
        "req2": User(id=uuid.uuid4(), email="req2@test.local", full_name="Req Two", password_hash=_HASH, role_id=ROLE_REQUESTER_ID),
    }
    db.add_all(users.values())
    resources = [SecurityResource(id=uuid.uuid4(), sequence_no=i, code=f"RES-{i:02d}", display_name=f"Resource {i:02d}",
                                  engineer_name=f"Secret Engineer {i}", engineer_email=f"eng{i}@offsec.local")
                 for i in (1, 2, 3)]
    db.add_all(resources)
    acts = [
        ActivityType(id=uuid.uuid4(), name="Web Application PT", base_duration_days=8),
        ActivityType(id=uuid.uuid4(), name="Segmentation PT", base_duration_days=5),
        ActivityType(id=uuid.uuid4(), name="Standalone LLM PT", base_duration_days=4, allow_additional_days=True, max_additional_days=2),
    ]
    db.add_all(acts)
    db.commit()
    db.close()
    yield {"users": users, "resources": resources, "acts": acts}


@pytest.fixture
def data(clean_db):
    return clean_db


class Api:
    def __init__(self, email: str):
        from app.main import app

        self.c = TestClient(app)
        r = self.c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]

    def _h(self, h=None):
        return {"X-CSRF-Token": self.csrf, **(h or {})}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)


@pytest.fixture
def admin(data):
    return Api("admin@test.local")


@pytest.fixture
def req1(data):
    return Api("req1@test.local")


@pytest.fixture
def req2(data):
    return Api("req2@test.local")


def booking_payload(data, resource_idx=0, act_idx=0, start=MON, **kw):
    p = {
        "application_name": "Customer Portal",
        "application_version": "1.0",
        "activity_type_id": str(data["acts"][act_idx].id),
        "pci_dss_scope": True,
        "resource_id": str(data["resources"][resource_idx].id),
        "start_date": start.isoformat(),
        "poc_name": "Jane POC",
        "poc_email": "jane.poc@example.com",
    }
    p.update(kw)
    return p
