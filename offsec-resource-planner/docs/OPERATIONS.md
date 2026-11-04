# Installation, deployment and operations

## 1. Production deployment checklist

1. Copy `.env.example` to `.env` and set:
   - `ORP_ENVIRONMENT=production`. Startup refuses a weak `ORP_SECRET_KEY` (<32 chars or a `dev-` value) or `ORP_COOKIE_SECURE=false`.
   - `ORP_SECRET_KEY` – random, ≥48 chars (`python -c "import secrets;print(secrets.token_urlsafe(48))"`).
   - `ORP_COOKIE_SECURE=true`.
   - `POSTGRES_PASSWORD`, plus the SMTP settings (`ORP_SMTP_*`; the password only in `ORP_SMTP_PASSWORD`).
   - `ORP_ENCRYPTION_KEY` – random and stable; encrypts SSO client secrets stored in the database.
   - `ORP_SEED=minimal`. This loads activity types, templates and settings only, with no demo accounts.
   - `ORP_APP_BASE_URL=https://<your host>`.
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

Environment (`ORP_*`): see `.env.example`. Runtime settings, editable under **Admin → Settings** and stored in
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
  SES SMTP, etc.): set `ORP_SMTP_HOST`, `ORP_SMTP_PORT`, `ORP_SMTP_STARTTLS=true` (or `ORP_SMTP_SSL=true`), plus the
  username and password.
- Delivery is asynchronous through the **worker**, which must be running. Admins can see delivery status, attempts
  and errors under **Admin → Email & Templates → Delivery log** and can requeue failures.
- For a provider that only offers an HTTP API (e.g. Graph sendMail), add a backend branch in
  `app/services/email_sender.deliver()`. Everything else (outbox, retry, logging) stays the same.

## 4. Background worker

`python -m app.worker` loops every `ORP_WORKER_INTERVAL_SECONDS` (default 30 s):

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

- Set `ORP_ENCRYPTION_KEY` (a stable random value) and back it up with the database. It encrypts stored client
  secrets; if it changes, re-enter the client secrets.
- Set the **Public application URL** in the SSO screen (or `ORP_APP_BASE_URL`) to the HTTPS address users reach.
  Redirect URIs are built from it.
- The backend must be able to reach the IdP over HTTPS (discovery, JWKS, token endpoints). Allow outbound access
  through any egress proxy.
- **Break-glass:** if an SSO misconfiguration locks everyone out, set `ORP_FORCE_LOCAL_LOGIN=true`, restart the
  backend, sign in with a local admin password at `/login?local=1`, fix the configuration, then remove the variable.

## 8. Upgrading

```bash
git pull
docker compose build
docker compose up -d        # the backend runs `alembic upgrade head` on start
```

New schema changes go in new Alembic revisions under `backend/alembic/versions/`.
