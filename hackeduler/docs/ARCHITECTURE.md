# Architecture

## 1. Overview

```
 Browser (React SPA)
   │  HttpOnly session cookie + X-CSRF-Token header
   ▼
 nginx (static SPA, security headers, TLS termination in front)  ──/api──►  FastAPI backend
                                                                              │  SQLAlchemy (parameterised)
                                                                              ▼
                                                                         PostgreSQL 16
                                                                              ▲
                                    Background worker (python -m app.worker) ─┘── SMTP / enterprise relay
```

The modules are separated as follows:

| Concern | Module |
|---|---|
| Authentication / sessions / CSRF / rate limiting | `app/security.py`, `app/deps.py`, `app/routers/auth.py` |
| Authorisation | `require_admin` router-level dependency on every `/api/admin/*` route, plus service-level checks |
| Working-day maths (pure) | `app/services/calendar_engine.py` |
| Availability (DB-backed, authoritative) | `app/services/availability.py` |
| Booking lifecycle and locking | `app/services/booking_service.py` |
| Conflicts | `app/services/conflicts.py` |
| Audit | `app/services/audit.py` + DB triggers |
| Notifications | `app/services/notifications.py` (outbox), `app/services/email_sender.py` (delivery) |
| Background jobs | `app/worker.py` |

The frontend only renders what the backend returns. It never calculates end dates or availability, and it never
decides authorisation. Hiding admin UI from requesters is a usability measure only; every check is enforced on the server.

## 2. Requirement analysis: assumptions and design decisions

| Topic | Decision |
|---|---|
| **Date ranges vs working days** | A booking reserves the *first N eligible working dates* from its start date for that resource. It does not reserve the whole calendar span. Weekends, holidays and leave days inside `[start, end]` are not reserved, so `end_date` is the last reserved working day. |
| **Eligible day** | A configured working weekday (default Mon–Fri, admin-configurable), not an organisation holiday, and not a leave day of *that* resource. |
| **"Today"** | Calculated in the organisation timezone (`timezone` setting, default `Asia/Kolkata`). Requesters can't start bookings in the past. Admins can, for record-keeping. |
| **Additional-duration rules** | Each activity type has `base_duration_days`, plus optional `allow_additional_days` / `max_additional_days`. A requester may add 0..max working days, and the backend validates the total. The seed uses this for *Standalone LLM PT* (+4). |
| **Duplicate activity names** | The spec lists *Hybrid … Single Codebase* at 12 **and** 16 days (same for Multiple Codebases). Both are seeded as separate activity types, unique on `(name, duration)`, with descriptions "Standard scope" and "Extended scope". |
| **Yellow ("limited")** | Capacity is one booking per resource-day, so partial allocation isn't modelled. Yellow instead means: when the user chooses an activity type, the day is free but a booking of that length starting there would hit an existing reservation or run out of eligible days. |
| **Expired status** | The spec lists five statuses. A sixth, **Expired**, is added so that auto-released pending requests aren't confused with requester or admin cancellations. Expiry is on by default (72 h, configurable) and can be turned off. |
| **Completed** | The worker moves approved bookings to Completed once `end_date < today`. |
| **Cancellation / reschedule policy** | Requesters can cancel their own **pending** requests directly (setting `requester_direct_cancel_pending`, on by default). For approved bookings, and for any reschedule, the requester submits a change request that an admin approves or declines. Approving a reschedule revalidates availability, and the old reservation is released only in the same transaction that creates the new one. |
| **Holiday or leave changes after booking** | The booking is never changed. It is flagged (`needs_review`) and a conflict is opened. Adding a non-working day on reserved dates opens a `holiday`/`leave` conflict and notifies the POC of an approved booking. Removing one opens a review conflict ("schedule may be shortened"). |
| **Approval revalidation** | On approval the server recomputes the working-day schedule against the *current* calendar. If it no longer matches the reserved dates (for example, a holiday was added) or overlaps another allocation, approval is blocked with an explanation. The admin can **Modify → Recalculate** and then approve, or Force Allocate. |
| **Admin-created bookings** | These are created as Approved by default (Pending is optional), with `source='admin'`. Admins can override the duration or set an explicit end date. In that case the booking reserves every eligible day in `[start, end]`. |
| **Automatic resource assignment** | Requesters choose only the activity and start date. The server assigns the active resource that can finish soonest, then the one with the lightest workload (reserved days from 30 days before to 90 days after the start), then the lowest resource number. Candidates are tried in that order inside savepoints, and the partial unique index decides any race, so concurrent requests fill different resources and never double-book. Admins can reassign any booking afterwards. |
| **Activities without a resource** | An activity type can have *Requires a security resource* turned off (for example an XBOW automated scan). Its duration is optional and the booking date is optional. No engineer is reserved, so it never affects availability or utilisation. It still goes through approval, is counted in all booking statistics, and is completed manually by an admin (**Mark completed**). A database CHECK keeps resource, dates and duration mandatory for resource-based bookings. |
| **Products and implementations** | Users and bookings carry a product and (optionally) an implementation. A requester's bookings are tagged with their product; they can pick any active implementation of that product. Requesters of the same product can **view** each other's bookings (My Bookings → product tab, calendar marker, booking details), but only the booking's author can cancel it or request changes. Dashboards and exports break bookings down by product, implementation and month. |
| **Deactivation from a date** | An admin can deactivate an engineer immediately or from a future date (`inactive_from`). Before that date the resource is bookable, but only for bookings that **finish before** it. From that date it shows as inactive (grey) and can't be booked. Pending or approved bookings that run on or after the date are not changed: they are flagged as `inactive_resource` conflicts and POCs of approved bookings are notified. The worker sets the resource inactive when the date arrives. Admins can cancel the schedule or Force Allocate past the date. |
| **Inactive resources** | They are excluded from new requester bookings and from preview. Existing bookings stay as they are and are flagged `inactive_resource`. Resource identifiers are sequence-based (`RES-NN` / `Resource NN`), never reused, and resources are never deleted. |
| **Authentication** | OpenID Connect SSO (Authorization Code + PKCE), configured by admins in the UI, plus optional local passwords (argon2id). Password sign-in can be allowed for everyone, restricted to admins (break-glass), or disabled. Both methods issue the same signed HttpOnly session cookie. See `SSO.md`. |
| **Email** | Plain-text emails only, using whitelist-based `{{Variable}}` substitution. Nothing in a template is evaluated, so templates can't inject markup or code. |

### Scheduling edge cases handled

- Start on a weekend, holiday or the resource's leave day: rejected, with the reason and a suggested next valid start.
- A duration that crosses several weekends, holidays and leave days: each one pushes the end date out.
- Leave only affects the resource it belongs to.
- Adjacent bookings (one ends Wednesday, the next starts Thursday) are allowed. Overlap on even one working day is blocked.
- A pending request past its expiry stops blocking immediately: availability ignores expired locks, and the next booking transaction sweeps them.
- Activity duration changes don't affect existing bookings, which keep a snapshot of name, base duration, additional days and total.
- A reschedule or reassignment that would conflict leaves the original reservation intact.
- When a reassignment involves two resources, both rows are locked in a deterministic order (sorted UUID) to avoid deadlocks.
- If a holiday is added between submission and approval, approval is blocked as `schedule_changed` instead of silently extending the booking.
- A Force Allocate can overlap an existing booking. A normal request can never overlap either of them.
- The CSV export neutralises spreadsheet formula injection.

## 3. Availability and locking strategy

### 3.1 Reservation model

`booking_resource_locks` stores **one row per (booking, resource, reserved working date)**:

```
lock_status: pending (blue) | confirmed (red) | released
is_forced:   true only for dates an admin deliberately double-booked via Force Allocate
expires_at:  pending expiry (null for confirmed)
```

Per-day rows model "working days" exactly: non-working days inside a booking's span are not locked. Overlap checks
become simple equality lookups backed by an index.

### 3.2 Preventing overlap under concurrency: two independent guarantees

1. **Serialisation by row lock.** Every operation that creates, moves or confirms a reservation runs in one
   transaction that first runs `SELECT … FROM security_resources WHERE id = :rid FOR UPDATE` (both resources,
   sorted, for a reassignment). Concurrent requests for the same resource queue on this lock. Each one then sweeps
   expired pending requests, recomputes the schedule from the *current* holidays, leave and locks, checks for
   conflicts and inserts its lock rows, all before committing. The check and the insert are therefore atomic:
   the second transaction only runs its check after the first has committed and can see its locks.

2. **Database constraint.**
   ```sql
   CREATE UNIQUE INDEX uq_lock_resource_day_active
     ON booking_resource_locks (resource_id, work_date)
     WHERE lock_status IN ('pending','confirmed') AND is_forced = FALSE;
   ```
   Even if a code path skipped the row lock, PostgreSQL rejects a second active, non-forced reservation of the same
   resource on the same day. The resulting `IntegrityError` is turned into HTTP **409**:
   > The selected resource is no longer available for the requested dates. Please select another resource or date.

Deadlocks and serialisation failures map to 409 `concurrent_update` ("please retry").

`tests/test_concurrency.py` releases 8 threads through a barrier, all requesting overlapping dates on one resource.
Exactly one succeeds and the other 7 get `resource_unavailable`. An HTTP-level test does the same with 6 clients, and
a third test inserts a conflicting lock directly to prove the unique index rejects it.

### 3.3 Lifecycle of a reservation

| Event | Locks |
|---|---|
| Submit | `pending` rows inserted (with `expires_at` if expiry is enabled) |
| Approve | revalidate → `pending` → `confirmed`, `expires_at = null` |
| Reject / cancel / expire | `→ released` |
| Reschedule / reassign / duration change | old rows `→ released` and new rows inserted **in the same transaction**. If anything fails the transaction rolls back and the old reservation is untouched. |
| Force Allocate | rows inserted. Only the dates that collide with another booking are `is_forced = true`, which exempts them from the unique index. |

## 4. Force Allocate: how it is restricted to admins

Force Allocate isn't a separate permission. It is an optional `force: {confirm: true, reason}` object that only
admin endpoints accept (`POST /api/admin/bookings`, `PATCH /api/admin/bookings/{id}`,
`POST /api/admin/bookings/{id}/approve`, `POST /api/admin/change-requests/{id}/decide`).

Enforcement layers:

1. **Router level.** Every `/api/admin/*` router is declared with `dependencies=[Depends(require_admin)]`. The role
   is loaded **from the database on every request**; the session token holds no role claim, and a forged token fails
   its signature check. A non-admin gets **403**, and the attempt is written to the audit log (`authorization.denied`).
2. **Schema level.** Requester input models use `extra='forbid'`, so sending `force`, `end_date`, `duration_days`
   or `status` to a requester endpoint is rejected with 422 and audited.
3. **Service level.** `booking_service.ensure_force_allowed()` raises 403 for any non-admin (audited as
   `force_allocate.denied`) and requires `confirm == true` and a non-blank reason.
4. **Workflow.** An admin request without `force` that hits a conflict or restriction gets
   **409 `override_required`**, carrying the mandated warning text, the list of issues, the conflicting bookings and
   their POCs, and the proposed plan. The UI shows these in `ForceAllocateDialog` (rendered only for admins), which
   needs a typed reason and a ticked confirmation before it resubmits with `force`.
5. **Safeguards on success.** No other booking is modified. The overlapping booking and its locks stay exactly as
   they were and are flagged `needs_review`. The app opens `overlapping_booking` and `manual_override` conflicts,
   notifies the POCs of impacted approved bookings, and writes an immutable `booking.force_allocated` audit entry.
   That entry records the admin, booking id, conflicting booking ids, affected dates, previous and new allocation,
   reason, acknowledged warning, timestamp and request id.

## 5. Audit trail

- `audit_logs` gets an entry in the **same transaction** as each change. Failed admin operations and denied
  attempts use a separate short transaction, because the business transaction is rolled back.
- Each entry captures: UUID, booking id, entity type and id, action, previous value (JSONB), new value (JSONB),
  actor id, email and role, reason, request/correlation id (`X-Request-ID`), client IP and timestamp.
- Entries are immutable: triggers reject `UPDATE`, `DELETE` and `TRUNCATE` on `audit_logs` and
  `booking_status_history`, and the API only exposes `GET /api/admin/audit`.
- Requesters only see a filtered history of their own bookings (status transitions and their change requests),
  with no actor identities, IPs or internal notes.

## 6. Notifications (transactional outbox)

Business transactions only `INSERT` rows into `email_notification_logs` with status `queued`. The worker claims
rows with `FOR UPDATE SKIP LOCKED`, sends them over SMTP, and records `sent`, or `attempts`/`last_error` with
exponential backoff (1, 2, 4, 8 min). After `max_attempts` (5) the row is marked `failed`, and an admin can requeue
it. Because delivery happens after commit and never touches booking rows, an SMTP outage can't roll back or corrupt
a booking, and a committed change never loses its notification.

## 7. Security controls summary

| Control | Implementation |
|---|---|
| Passwords | argon2id (`argon2-cffi`). Policy: ≥12 chars with 3 character classes. Timing-equalised verification for unknown users. |
| SSO | OIDC Authorization Code + PKCE (S256); `state` and `nonce` in an encrypted 10-minute HttpOnly cookie; ID-token signature checked via JWKS (asymmetric algorithms only); `iss`/`aud`/`exp`/`iat`/`nonce`/`azp` validated; client secret encrypted at rest and write-only in the API; no open redirects; email-linking can't take over an already-linked account; last active admin can't be demoted by group sync |
| Sessions | HS256-signed token in an `HttpOnly; SameSite=Lax; Secure` (prod) cookie, 8 h expiry, revoked server-side via `token_version` on logout, password change, role change or deactivation |
| CSRF | Double-submit token. The header must match both the cookie and the value bound inside the signed session |
| Rate limiting | Per-IP global limit plus per-IP and per-account login limits (in-process; use a shared store for multi-instance) |
| Injection | SQLAlchemy parameterised queries only. Plain-text emails. Template whitelist. CSV formula neutralisation |
| IDOR | Requester endpoints filter by `requester_id` and return **404** for other users' bookings |
| Identity protection | Requester schemas contain no engineer fields. The requester calendar grid is built without names, and leave type and reason are never exposed |
| Headers | CSP, X-Frame-Options DENY, nosniff, Referrer-Policy, HSTS (prod), `Cache-Control: no-store` on the API |
| Secrets | Env only (`HACKEDULER_SECRET_KEY`, `HACKEDULER_SMTP_PASSWORD`, DB password). Never stored in the DB or returned by the API. Production startup refuses weak keys or insecure cookies |
| Transport | HTTPS required in production (terminate TLS in front of nginx) |
