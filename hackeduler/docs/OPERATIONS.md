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
2. Choose the port, DNS name and HTTPS: `./deploy.sh --domain <name> --https files|auto`, or use your existing web server. See [`NETWORK.md`](NETWORK.md). Don't expose `backend` or `db` directly.
3. `docker compose up -d --build`. Leave out `--profile dev` in production so Mailpit doesn't start.
4. The first admin is created by `./deploy.sh` on the very first install (`admin@hackeduler.local`, or set
   `HACKEDULER_INITIAL_ADMIN_EMAIL`), and the generated password is printed once. To create or reset an admin later:
   `docker compose exec backend python -m app.manage create-admin you@corp.example`
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

New settings (Admin → Settings → Activity initiation email): `initiation_email_enabled` (default on) and
`initiation_email_days_before` (default 7). Per activity type, admins can override the number of days or switch the
email off, and edit the checklist of details it asks for. The wording is the editable template
`activity_initiation_poc` under Email & Templates. New-user and engineer emails use the templates `user_welcome`
(sent only for SSO-only accounts, with the sign-in URL from `public_base_url`) and `booking_confirmed_engineer`
(sent to each assigned engineer's email when a booking becomes approved).

`python -m app.worker` loops every `HACKEDULER_WORKER_INTERVAL_SECONDS` (default 30 s):

1. expires pending bookings past `expires_at` (releases locks, notifies the POC/requester, audits the change)
2. deactivates resources whose scheduled **inactive-from** date has arrived
3. marks approved bookings whose end date has passed as **Completed**
4. queues the **Activity initiation** email for approved bookings whose send date (start date minus the configured days) has arrived; once per start date
5. delivers queued emails, with retry and backoff

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

**One command for every install and every upgrade:**

```bash
cd hackeduler
git pull            # or copy the new version's files over the old ones (keep .env and backups/)
./deploy.sh
```

`deploy.sh` never deletes data. Each run it:

1. Creates `.env` with random secrets on the very first install only. After that `.env` is yours and is kept.
2. Renames old `ORP_*` settings to `HACKEDULER_*` (the old file is saved as `.env.bak`).
3. Finds the database volume that holds your data, including the pre-rename `offsec-resource-planner_pgdata`, and
   refuses to start if a configured volume is missing instead of silently using an empty database.
4. **Backs up the database** to `backups/pre-deploy-<timestamp>.dump` before changing anything, and stops if the
   backup fails.
5. Rebuilds and restarts the containers. Database migrations run automatically, only add tables and columns, and
   run once each.
6. Waits until the app is healthy, and shows the logs if it isn't.

### Why data can't be lost

- **The database volume is external** (`external: true` in `docker-compose.yml`). Docker Compose never creates or
  deletes it, so `docker compose down`, `docker compose down -v`, rebuilds, folder renames and new checkouts all
  leave it alone. Only an explicit `docker volume rm <name>` removes it.
- **Automatic backups.** The `backup` service writes `backups/auto-<timestamp>.dump` every 24 hours and keeps 14
  days. Change this with `HACKEDULER_BACKUP_INTERVAL_HOURS` / `HACKEDULER_BACKUP_KEEP_DAYS`. Pre-deploy and manual
  backups are never pruned. Copy `backups/` to another machine or storage regularly.
- **Manual backup at any time:** `./scripts/backup-db.sh`.

Keep `HACKEDULER_SEED=none` (or `minimal`) on a system with real data. `demo` re-creates demo accounts you deleted.

### Restoring a backup

```bash
./scripts/restore-db.sh backups/hackeduler-YYYYMMDD-HHMMSS.dump   # asks for confirmation, replaces current data
```

New schema changes go in new Alembic revisions under `backend/alembic/versions/`. Never edit an existing one.
