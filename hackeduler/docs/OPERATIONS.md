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
| `admin_notification_recipients` | `[…]` | Recipients of new-request and change-request emails: ONE email addressed To all of them (everyone sees who else got it), not one email each |
| `email_cc_recipients` | `[]` | Up to 10 addresses copied (Cc) on **every** email Hackeduler sends, initiation email included. Skipped where that address is already the recipient. Applied when the email is sent, so queued emails pick up a change. The admin "Send test email" is not copied |
| `notify_requester_copy` | `true` | Copy the requester on POC emails |
| `smtp_host/port/username/starttls` | `null` (= env) | Non-secret SMTP overrides |

## 3. Email

- Backends: `smtp` (default), `console` (writes messages to the worker log), `memory` (tests).
- **Amazon SES (optional, alongside SMTP).** Admin -> Settings -> Email lets you pick the **primary** service (SMTP or SES), an
  optional **fallback** tried when the primary fails, the SES region and configuration set, and has **Send test email** buttons
  for each service. The delivery log shows which service sent each message. Prerequisites: the sender address (or domain) is a
  verified identity in SES in that region (and the account is out of the SES sandbox, or the recipients are verified), and
  permission to `ses:SendRawEmail`: with an IAM **role** on the server (e.g. EC2 instance role) nothing needs configuring (the
  container needs metadata hop limit 2); otherwise put an IAM user's keys in `.env` as `AWS_ACCESS_KEY_ID` and
  `AWS_SECRET_ACCESS_KEY` (never in the UI or database). Then `./deploy.sh` (or `docker compose up -d --build`) so the backend image gets the AWS library. The same
  settings can be preset with `HACKEDULER_EMAIL_PRIMARY`, `HACKEDULER_EMAIL_FALLBACK`, `HACKEDULER_AWS_REGION`.
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
`activity_initiation_poc` under Email & Templates. All emails to the POCs (approved, rejected, modified, cancelled, impacted, expired, change request declined, initiation) are ONE email addressed To every POC (not one email per POC). The initiation email is ONE email addressed To the POC(s) (plus the requester when the requester-copy setting applies), with the assigned engineer(s) in Cc (and the Settings Cc list after them). New-user and engineer emails use the templates `user_welcome`
(sent only for SSO-only accounts, with the sign-in URL from `public_base_url`) and `booking_confirmed_engineer`
(sent to each assigned engineer's email when a booking becomes approved).

### Email design: visual editor, logo and footer

**Admin → Email & Templates → Edit** opens a visual editor: format with buttons (bold, italic, heading, bullet list, link,
details table, button), click a variable chip to insert `{{Name}}` at the cursor, and see the real email in a live preview
that can be switched between **Desktop** and **Phone**. Pick one of three designs (Classic, Minimal, Banner) and a colour
(14 presets or any custom colour) per template.
The body editor also has **tables**: a label/value *Details table*, or a data table (choose rows and columns, add or remove rows and
columns, header row on/off) with banded rows. Variables work inside any cell, and the plain-text copy shows rows as `a | b | c`.

Every notification is sent as `text/plain` + `text/html` with the Hackeduler logo header (embedded in the message, so it shows
even when the client blocks remote images) and the footer ("Designed and developed by OffSec Team, InfoSec, IBS Group").
The HTML is responsive: on a phone the details table stacks and buttons go full width. Body HTML is cleaned on the server
(no scripts, images, event handlers or non-http(s) links) and placeholder values are escaped, so a name or comment can never
inject markup. Templates written in the older text style (`**bold**`, `- ` bullets) keep sending unchanged until they are opened
and saved in the visual editor, which converts them. Migrations `0017` and `0018` (new nullable/defaulted columns only) run
automatically on `./deploy.sh`.


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

### Activity types: "Details to ask the POC for"

On **Admin → Activity Types → Edit** (with the Activity initiation email on) this field is a visual editor with the same
formatting as the template editor plus **tables** (choose rows and columns, add or remove rows and columns, header row on/off).
The content replaces `{{Required Details}}` in the Activity initiation email as a formatted block; a preview below the editor
shows it on Desktop and Phone, and the plain-text copy of the email shows tables as `Role | Accounts` lines. Leave the field empty
to use the built-in checklist. Values saved earlier in the old text style (`- ` bullets) keep working and are converted when
opened. No database change: the field already holds free text, and rich content is detected by its tags. The HTML is cleaned when
sent (no scripts, images, event handlers or non-http(s) links).

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

### Who is copied on "Booking modified"

The Booking modified email is ONE message: To the POC(s) (and the requester copy, if enabled), with the assigned security engineer(s)
in Cc. When the resource is changed, the previous engineer is copied as well, so the person who loses the booking is told too.
The default template now includes `{{Engineer Names}}`; templates you already edited keep their text, so add the line in
Email & Templates if you want it shown. No database change.
If the POC list was changed, the people taken off it get the update in a second email, sent only to them (nobody gets it twice).

The engineers' "Booking confirmed" email (sent on approval) is also ONE email addressed To all assigned engineers; its greeting
reads "Hello Name1, Name2,".

### Admin screens: deep link to a booking

`/admin/bookings?booking=<booking id>` opens the Bookings page with that booking's details window already open (the address is
updated when a row is opened and cleared when the window is closed; other filters in the address are kept). In **Team Calendar**,
the application name and version in the day popup link there, so the booking can be opened in the same tab or, with Ctrl/Cmd-click,
a new tab. No backend or database change.

### Users page: counts and search

**Admin → Users** shows a summary strip at the top (users shown, by Role, by Sign-in — SSO / Password / SSO not yet signed in — and by
Status — Active / Disabled, plus Deleted when "Show deleted" is on) and a search box that matches any column in the table (name, email,
role, resource, products, implementation, sign-in, status, last login). Several words must all match. The counts follow the search.
Frontend only; no backend or database change.

### Yearly booking limit per activity type

**Admin → Activity types → Edit → "Bookings accepted per calendar year"** sets a maximum for that type (empty = unlimited, the default).
The year is the calendar year of the booking's start date (for a request with no date, the year it is approved). A booking uses the balance
once an admin **approves** it (approved or completed); pending, rejected, cancelled and expired requests do not. Example: limit 10 for 2027 means
the first requester sees "Balance for 2027: 10 of 10", and after one approval the next requester sees 9.

When the year is full, requesters cannot submit that type for that year and the booking form says so; an admin cannot approve another pending
request until the limit is raised (bookings created by an admin directly, e.g. Manual Allocation, still count but are never blocked).
Manual Allocation shows the same balance (for the year of the chosen date) when a limited activity is selected; if the year is full it
says so, but admins can still create the booking.
Requires migration 0019 (`./deploy.sh` runs it; it only adds a nullable column, existing data is untouched).

### Product and implementation tags

**Admin → Products → Edit** (on a product or an implementation) has a **Tags** field: type a tag and press Enter or comma; up to 20 tags
of 40 characters each. Tags are only for grouping, nothing else changes. The **Admin Dashboard** gets a **Tag** drop-down next to the
Product filter (shown once any tag exists); choosing a tag limits every KPI and chart to bookings whose product **or** implementation has
that tag (case-insensitive), and combines with the Product and date filters. The CSV/Excel download from the dashboard follows the tag too.
Requires migration 0020 (adds an empty tag list to both tables; existing data is untouched).

### My Bookings: PCI scope and search

**My Bookings** (requester) has a **PCI scope** column (a "PCI" badge when the booking is in PCI DSS scope, otherwise "Not in scope"; sortable)
and a search box that matches every column in the table (application, booking id, version, requested by, product, implementation, activity,
PCI, resource, dates, status, report, submitted). Several words must all match. Search runs in the browser on the loaded list, so it is
instant; the status tabs and "My bookings / product bookings" switch still filter on the server. The full booking id is shown on this page
and on the admin Bookings page. Frontend only.
