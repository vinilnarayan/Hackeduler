# Installation, deployment and operations

## 1. Production deployment checklist

1. Copy `.env.example` to `.env` and set:
   - `HACKEDULER_ENVIRONMENT=production`. Startup refuses a weak `HACKEDULER_SECRET_KEY` (<32 chars or a `dev-` value) or `HACKEDULER_COOKIE_SECURE=false`.
   - `HACKEDULER_SECRET_KEY` – random, ≥48 chars (`python -c "import secrets;print(secrets.token_urlsafe(48))"`).
   - `HACKEDULER_COOKIE_SECURE=true`.
   - `POSTGRES_PASSWORD`, plus the SMTP settings (`HACKEDULER_SMTP_*`; the password only in `HACKEDULER_SMTP_PASSWORD`).
   - `HACKEDULER_ENCRYPTION_KEY` – random and stable; encrypts SSO client secrets stored in the database.
   - `HACKEDULER_SEED=minimal`. This loads activity types, templates and settings only, with no demo accounts.
   - `HACKEDULER_APP_BASE_URL=https://<your host>`.
2. Terminate **HTTPS** in front of the `frontend` container (corporate load balancer, Traefik, or an nginx 443 block). Don't expose `backend` or `db` directly.
3. `docker compose up -d --build`. Leave out `--profile dev` in production so Mailpit doesn't start.
4. Create the first admin:
   ```bash
   docker compose exec backend python - <<'PY'
   import uuid
   from app.db import SessionLocal
   from app.models import User, ROLE_ADMIN_ID
   from app.security import hash_password
   db = SessionLocal()
   db.add(User(id=uuid.uuid4(), email="you@corp.example", full_name="Your Name",
               password_hash=hash_password("<strong password>"), role_id=ROLE_ADMIN_ID))
   db.commit()
   PY
   ```
5. Sign in, configure **Single Sign-On** (see `SSO.md`), then add resources (engineers), holidays (CSV/Excel import) and settings: admin notification recipients and sender.
   With SSO auto-provisioning, users don't need to be created manually.
6. Database role hardening: give the application a non-superuser role. See `DATABASE.md` → Immutability.

### Scaling notes

- The API is stateless. Run several backend replicas behind the proxy. The in-process rate limiter is then
  per-replica; use a shared limiter (e.g. a Redis-backed gateway policy) for strict global limits.
- More than one worker can run safely, because outbox rows are claimed with `FOR UPDATE SKIP LOCKED` and expiry
  uses `SKIP LOCKED`.

## 2. Configuration reference

Environment (`HACKEDULER_*`): see `.env.example`. Runtime settings, editable under **Admin → Settings** and stored in
`application_settings`:

| Key | Default | Meaning |
|---|---|---|
| `timezone` | `Asia/Kolkata` | Organisation timezone for "today" |
| `working_weekdays` | `[0,1,2,3,4]` | Mon–Fri |
| `pending_expiry_enabled` / `pending_expiry_hours` | `true` / `72` | Auto-release of unreviewed pending reservations |
| `requester_direct_cancel_pending` | `true` | Requesters can cancel their own pending requests without approval |
| `email_sender_name` / `email_sender_address` | — | From header |
| `admin_notification_recipients` | `[…]` | Recipients of new-request and change-request emails |
| `notify_requester_copy` | `true` | Copy the requester on POC emails |
| `smtp_host/port/username/starttls` | `null` (= env) | Non-secret SMTP overrides |

## 3. Email

- Backends: `smtp` (default), `console` (writes messages to the worker log), `memory` (tests).
- Use any SMTP relay or enterprise provider with SMTP submission (Microsoft 365 / Exchange, Google Workspace relay,
  SES SMTP, etc.): set `HACKEDULER_SMTP_HOST`, `HACKEDULER_SMTP_PORT`, `HACKEDULER_SMTP_STARTTLS=true` (or `HACKEDULER_SMTP_SSL=true`), plus the
  username and password.
- Delivery is asynchronous through the **worker**, which must be running. Admins can see delivery status, attempts
  and errors under **Admin → Email & Templates → Delivery log** and can requeue failures.
- For a provider that only offers an HTTP API (e.g. Graph sendMail), add a backend branch in
  `app/services/email_sender.deliver()`. Everything else (outbox, retry, logging) stays the same.

## 4. Background worker

`python -m app.worker` loops every `HACKEDULER_WORKER_INTERVAL_SECONDS` (default 30 s):

1. expires pending bookings past `expires_at` (releases locks, notifies the POC/requester, audits the change)
2. deactivates resources whose scheduled **inactive-from** date has arrived
3. marks approved bookings whose end date has passed as **Completed**
4. delivers queued emails, with retry and backoff

`python -m app.worker --once` runs a single pass (suitable for cron). Admins can also trigger steps 1–3 with
`POST /api/admin/jobs/run`.

## 5. Conflict resolution workflow (admins)

Conflicts are opened automatically when:

| Trigger | Conflict type |
|---|---|
| A holiday is added or moved onto reserved working days | `holiday` |
| A holiday is removed or moved away from a booked span | `holiday` (schedule may now be shorter) |
| Leave is added or changed on a resource's reserved days | `leave` |
| Leave is cancelled or shortened inside a booked span | `leave` |
| A resource with bookings on or after its deactivation date is deactivated, immediately or from a date | `inactive_resource` |
| Force Allocate | `manual_override`, plus `overlapping_booking` for each overlapped booking |

The system never moves, cancels or reassigns a booking on its own. To resolve a conflict:

1. Open **Admin → Conflicts** (filter: Open), then open the booking from the conflict row.
2. Review the description, affected dates, the conflicting booking and POC details, and the audit history.
3. Choose an action on the booking's **Modify / Reassign** tab (each one is revalidated, audited, and emailed to
   the POC of an approved booking):
   - **Keep** (e.g. a backup engineer covers the leave day): no booking change.
   - **Recalculate** the duration against the new calendar (extends or shortens the end date).
   - **Reschedule** to a new start date.
   - **Reassign** to another resource.
   - **Cancel** the booking (with a reason).
   - If the only remaining option overlaps another booking, **Force Allocate** with a reason and explicit confirmation.
4. Coordinate with the POC if the dates changed.
5. Click **Resolve** and record the resolution note. Once all of a booking's conflicts are resolved, its
   `needs_review` flag clears. Resolved conflicts stay visible under the Resolved filter.

## 6. Backups and monitoring

- Back up PostgreSQL daily (`pg_dump -Fc`) and keep point-in-time WAL archives if possible. Test restores.
- Health endpoint: `GET /api/health` (checks DB connectivity).
- Monitor `email_notification_logs` for rows with `status='failed'`, open `booking_conflicts`, and worker logs.
- Logs never contain passwords, session tokens or SMTP credentials.

## 7. Single sign-on

SSO is built in and configured entirely under **Admin → Single Sign-On**. See [`SSO.md`](SSO.md) for step-by-step
provider set-up, role mapping and the break-glass procedure. Operationally:

- Set `HACKEDULER_ENCRYPTION_KEY` (a stable random value) and back it up with the database. It encrypts stored client
  secrets; if it changes, re-enter the client secrets.
- Set the **Public application URL** in the SSO screen (or `HACKEDULER_APP_BASE_URL`) to the HTTPS address users reach.
  Redirect URIs are built from it.
- The backend must be able to reach the IdP over HTTPS (discovery, JWKS, token endpoints). Allow outbound access
  through any egress proxy.
- **Break-glass:** if an SSO misconfiguration locks everyone out, set `HACKEDULER_FORCE_LOCAL_LOGIN=true`, restart the
  backend, sign in with a local admin password at `/login?local=1`, fix the configuration, then remove the variable.

## 8. Upgrading without losing data

Your data is stored in the Docker volume **`hackeduler_pgdata`** (set by `HACKEDULER_DB_VOLUME`), not inside the
containers. Rebuilding or replacing containers never touches it. On start the backend runs the database migrations
(`alembic upgrade head`). They only **add** tables and columns, and each one runs exactly once.

### What deletes data (never do these on a live system)

| Command | Effect |
|---|---|
| `docker compose down -v` | `-v` **deletes the database volume** |
| `docker volume rm …_pgdata` / `docker volume prune` | deletes the volume |
| Changing `HACKEDULER_DB_VOLUME` or `POSTGRES_DB` to a new name | starts an **empty** database (the old data still exists, but isn't used) |

`docker compose down` (without `-v`), `docker compose up -d --build`, `docker compose restart`, and rebooting the
server are all safe.

### Standard upgrade

```bash
cd hackeduler
./scripts/backup-db.sh                 # 1. backup -> backups/hackeduler-<timestamp>.dump
git pull                               # 2. get the new version (or copy the new files over)
docker compose up -d --build           # 3. rebuild & restart; migrations run automatically
docker compose logs backend | grep -i -E "alembic|error"   # 4. check migrations applied
```

Keep `HACKEDULER_SEED=none` (or `minimal`) on a system with real data. `demo` re-creates the demo accounts if you
deleted them.

### Upgrading a deployment created before the rename to Hackeduler

Earlier versions lived in a folder called `offsec-resource-planner/` and used `ORP_*` settings. Docker named the
database volume after that folder (`offsec-resource-planner_pgdata`).

1. **Back up first**, from the *old* folder while it is still running:
   `docker compose exec -T db pg_dump -U <POSTGRES_USER> -d <POSTGRES_DB> -Fc > before-upgrade.dump`
2. Check the volume name that holds your data: `docker volume ls | grep pgdata`
3. Stop the old stack **without `-v`**: `docker compose down`
4. Copy your existing `.env` into the new `hackeduler/` folder, and add:
   ```
   HACKEDULER_DB_VOLUME=offsec-resource-planner_pgdata
   ```
   Keep `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD` exactly as they were.
5. Rename the `ORP_` prefix to `HACKEDULER_` in `.env`, keeping every value the same. Old `ORP_*` names still work
   for now (the backend logs a warning), but rename them. Keeping `ORP_SECRET_KEY` / `ORP_ENCRYPTION_KEY` values
   unchanged matters: they decrypt stored SSO client secrets.
6. `docker compose up -d --build` from the `hackeduler/` folder. Compose may print a warning that the volume
   "was created for project offsec-resource-planner". That's expected; it uses the existing data.
7. Sign in and check your data. Everyone has to sign in again once, because the session cookie names changed.

### Restoring a backup

```bash
./scripts/restore-db.sh backups/hackeduler-YYYYMMDD-HHMMSS.dump   # asks for confirmation, replaces current data
```

New schema changes go in new Alembic revisions under `backend/alembic/versions/`. Never edit an existing one.
