# Hackeduler

Internal web application for managing an Offensive Security team's capacity: anonymous, colour-coded resource
availability for requesters; working-day based slot calculation; pending reservations with database-level locking;
admin approval, leave, holidays, conflict management, admin-only **Force Allocate**, an immutable audit trail and
email notifications. Users sign in with **single sign-on (OpenID Connect: Microsoft Entra ID, Okta, Google
Workspace, Keycloak, or any OIDC provider)** and/or local passwords. Everything is configured under
**Admin → Single Sign-On**.

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Tailwind CSS 4, Lucide icons, Recharts, custom resource-lane calendar |
| Backend | Python 3.13, FastAPI, SQLAlchemy 2, Pydantic 2, Alembic |
| Database | PostgreSQL 16 (row locks, partial unique index, append-only triggers) |
| Background | `app.worker` – email outbox delivery with retries, pending-reservation expiry, completion |
| Deployment | Docker Compose (db, backend, worker, nginx frontend, optional Mailpit) |

Documentation:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) – architecture, assumptions & edge cases, the availability and locking strategy, how Force Allocate is restricted to admins
- [`docs/DATABASE.md`](docs/DATABASE.md) – schema, constraints and indexes
- [`docs/API.md`](docs/API.md) – REST API reference (interactive OpenAPI docs are at `/api/docs`)
- [`docs/SSO.md`](docs/SSO.md) – single sign-on set-up (Entra ID, Okta, Google, Keycloak), role mapping, sign-in policy, break-glass
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) – deployment, configuration, email, backups, the conflict resolution workflow

---

## Quick start (Docker)

```bash
cd hackeduler
cp .env.example .env          # then edit secrets (POSTGRES_PASSWORD, HACKEDULER_SECRET_KEY)
docker compose --profile dev up -d --build
```

- App: <http://localhost:8080>
- API docs: <http://localhost:8080/api/docs>
- Mailpit (captured notification emails): <http://localhost:8025>

The backend container runs migrations on start. With `HACKEDULER_SEED=demo` it also seeds sample data.

### Local development test accounts (seeded with `HACKEDULER_SEED=demo`)

| Role | Email | Password |
|---|---|---|
| Admin | `admin@offsec.local` | `Admin@12345678` |
| Requester | `requester@offsec.local` | `Requester@12345` |
| Requester | `requester2@offsec.local` | `Requester@12345` |

> These accounts are for local development only. Use `HACKEDULER_SEED=minimal` or `none` in production and create real accounts under **Admin → Users**.

The seed also creates 6 resources (Resource 01–06 mapped to sample engineers), every activity type from the
requirements, sample holidays for the current and next year, one leave record, and sample bookings in each status.

---

## Running without Docker

Prerequisites: Python 3.12+, Node 20+, PostgreSQL 14+.

```bash
# database
createdb hackeduler

# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export HACKEDULER_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/hackeduler
export HACKEDULER_EMAIL_BACKEND=console            # print emails to the log instead of sending
alembic upgrade head
python -m app.seed                          # demo data + test accounts
uvicorn app.main:app --reload --port 8000
python -m app.worker                        # separate terminal: email outbox, expiry, completion

# frontend (separate terminal)
cd frontend
npm install
npm run dev                                 # http://localhost:5173 (proxies /api to :8000)
```

## Tests

```bash
# backend – needs a real PostgreSQL database (dropped and recreated by the tests)
createdb hackeduler_test
cd backend
HACKEDULER_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/hackeduler_test pytest -q

# frontend
cd frontend
npm test
npm run typecheck
```

The backend suite has 142 tests, including 45 SSO tests against an in-process fake identity provider (signature,
issuer, audience, expiry, nonce, state, PKCE, algorithm confusion, key rotation, group and domain restrictions,
account-linking takeover protection, sign-in policy and lockout protection). It also covers: working-day engine unit tests, API integration tests, concurrent booking races
(8 threads at the service layer and 6 parallel HTTP clients), RBAC and IDOR tests, Force Allocate restrictions,
audit immutability, email outbox failure and retry, and a test for each acceptance criterion. The frontend tests
cover the Force Allocate dialog gating and the status and colour helpers.

### Acceptance criteria → tests

| # | Criterion | Test(s) |
|---|---|---|
| 1, 17 | Requester can't see engineer names, audit | `test_auth_rbac.py::test_requester_calendar_hides_engineer_names`, `test_requester_resource_listing_is_anonymous`, `test_requester_cannot_access_audit_records` |
| 2 | Configure resources, activity types, durations | `test_booking_flow.py::test_activity_duration_change_does_not_alter_existing_booking`, `test_deactivation_preserves_history_and_blocks_new_bookings` |
| 3, 4, 5, 6 | Leave/holidays, working-day maths, no non-working start | `test_calendar_engine.py::*`, `test_booking_flow.py::test_availability_preview_calculates_end_date_with_holiday`, `test_leave_only_affects_its_resource`, `test_cannot_start_on_non_working_day` |
| 7 | Pending & approved block overlaps | `test_booking_flow.py::test_pending_and_approved_block_overlaps` |
| 8, 9 | Simultaneous requests – exactly one wins | `test_concurrency.py::*` |
| 10, 11 | Rejected/cancelled/expired release | `test_rejection_requires_reason_releases_and_notifies`, `test_cancellation_releases`, `test_pending_expiry_releases`, `test_worker_expires` |
| 12 | Approval revalidates | `test_approval_revalidates_after_holiday_added` |
| 13, 14 | Reject reason + POC emails | `test_rejection_requires_reason_releases_and_notifies`, `test_approval_notifies_poc_and_confirms_locks` |
| 15 | UUID v4 | `test_submission_creates_uuid4_pending_booking_with_snapshot` |
| 16 | No access to others' bookings | `test_auth_rbac.py::test_requester_cannot_see_other_requesters_booking` |
| 18–22 | Force Allocate admin-only, reason/warning/confirm, non-destructive, audited | `test_force_allocate.py::*` |
| 23 | Previous details preserved | `test_admin_modification_preserves_previous_values_in_audit` |
| 24, 25 | Leave/holiday flags; conflicts tracked | `test_leave_after_approval_flags_for_review`, `test_holiday_delete_flags_spanning_booking` |
| 26 | Changes notify POC | `test_admin_modification_preserves_previous_values_in_audit`, `test_reschedule_request_flow` |
| 27 | Email failure doesn't roll back | `test_audit_and_email.py::test_email_failure_is_logged_retried_and_does_not_affect_booking` |
| 28 | History after deactivation | `test_deactivation_preserves_history_and_blocks_new_bookings` |

## Project layout

```
hackeduler/
├── backend/
│   ├── alembic/versions/0001_initial_schema.py   # authoritative DDL (constraints, indexes, triggers)
│   ├── app/
│   │   ├── main.py            # FastAPI app, middleware (request id, rate limit, headers), error handlers
│   │   ├── config.py          # env-based settings (secrets env-only)
│   │   ├── security.py        # argon2 hashing, signed session cookie, CSRF, rate limiter
│   │   ├── deps.py            # authentication + require_admin
│   │   ├── models.py / schemas.py
│   │   ├── services/
│   │   │   ├── calendar_engine.py   # pure working-day arithmetic
│   │   │   ├── availability.py      # backend-authoritative availability + calendar grid
│   │   │   ├── booking_service.py   # lifecycle, locking, Force Allocate
│   │   │   ├── conflicts.py         # flag/resolve conflicts
│   │   │   ├── sso.py               # OpenID Connect: discovery, PKCE, token validation, provisioning
│   │   │   ├── crypto.py            # encryption of stored secrets (SSO client secrets)
│   │   │   ├── audit.py             # append-only audit writer
│   │   │   ├── notifications.py     # templates + transactional outbox
│   │   │   ├── email_sender.py      # SMTP delivery with retry
│   │   │   └── settings_service.py
│   │   ├── routers/           # auth, sso, requester, admin_config, admin_bookings, admin_reports
│   │   ├── worker.py          # background jobs
│   │   └── seed.py
│   └── tests/
├── frontend/src/
│   ├── components/ResourceCalendar.tsx, ForceAllocateDialog.tsx, AdminBookingModal.tsx, ...
│   └── pages/{requester,admin}/...
├── docs/
├── docker-compose.yml
└── .env.example
```
