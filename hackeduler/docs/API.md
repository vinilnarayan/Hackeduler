# REST API

Interactive OpenAPI documentation is served at **`/api/docs`** (Swagger UI) and `/api/redoc`. The machine-readable
schema is at `/api/openapi.json`.

## Conventions

- **Auth:** `POST /api/auth/login` sets an HttpOnly session cookie (`hackeduler_session`) and a CSRF cookie (`hackeduler_csrf`).
  Every `POST/PUT/PATCH/DELETE` must send `X-CSRF-Token: <value of hackeduler_csrf>`.
- **Roles:** all `/api/admin/*` endpoints require the Admin role. Everything else requires any authenticated user.
- **Errors:** `{"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}`

| Status | Typical codes |
|---|---|
| 401 | `not_authenticated`, `invalid_credentials` |
| 403 | `forbidden`, `csrf_failed` |
| 404 | `not_found` (also returned for other requesters' bookings) |
| 409 | `resource_unavailable`, `override_required`, `invalid_state`, `booking_expired`, `duplicate_request`, `concurrent_update` |
| 422 | `validation_error`, `past_date`, `override_reason_required`, `confirmation_required`, `no_changes` |
| 429 | `rate_limited` |

- **Correlation:** send `X-Request-ID` (≤64 chars, `[A-Za-z0-9-_.]`) or one is generated. It is echoed in the
  response and stored on audit entries.
- Dates are ISO `YYYY-MM-DD`; timestamps are ISO-8601 UTC.

## Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | `{email, password}` → `{user, csrf_token}` + cookies. Rate limited |
| POST | `/api/auth/logout` | Revokes all sessions of the user |
| GET | `/api/auth/me` | Current user + CSRF token |
| POST | `/api/auth/change-password` | `{current_password, new_password}` |

## Single sign-on (public)

| Method | Path | Description |
|---|---|---|
| GET | `/api/auth/sso/providers` | Enabled providers `{slug, display_name, provider_type}`, `local_login_mode`, `auto_redirect` |
| GET | `/api/auth/sso/{slug}/login[?next=/path]` | 302 to the IdP (sets the encrypted `hackeduler_sso_tx` cookie) |
| GET | `/api/auth/sso/{slug}/callback` | Redirect URI to register at the IdP. On success: session cookies + 302 to `next`; on failure: 302 to `/login?sso_error=<code>` |

`POST /api/auth/login` returns **403 `local_login_disabled`** when the password policy forbids it.
`POST /api/auth/logout` returns `sso_logout_url` when the provider has single logout enabled.

## Requester (any authenticated user)

| Method | Path | Description |
|---|---|---|
| GET | `/api/resources` | Anonymous resources `{id, code, display_name, is_active}` |
| GET | `/api/activity-types` | Active activity types |
| GET | `/api/holidays?start&end` | Holidays |
| GET | `/api/settings/public` | Timezone, today, working weekdays, expiry and cancellation policy |
| GET | `/api/calendar?start&end[&activity_type_id]` | Anonymous availability grid (≤ ~6 months) |
| POST | `/api/availability/auto` | `{activity_type_id, start_date?, additional_days?}` → the resource that would be assigned, end date, or `suggested_start_date` |
| POST | `/api/availability/check` | Slot calculation for a specific resource |
| POST | `/api/bookings` | Submit booking. `resource_id` optional (omit = auto-assign); `start_date` optional for activities without a resource; `implementation_id` optional (must belong to the requester's product). 409 `no_resource_available` includes `suggested_start_date` |
| GET | `/api/bookings/mine?status&q&scope=mine\|product&implementation_id` | Own bookings, or all bookings of the caller's product |
| GET | `/api/bookings/{id}` | Own or same-product booking (404 otherwise); `is_mine` tells whether the caller may change it |
| GET | `/api/me/implementations` | The caller's product and its active implementations |
| GET | `/api/bookings/{id}/history` | Filtered status / change-request history |
| POST | `/api/bookings/{id}/cancel` | `{reason}`. Direct cancel of own **pending** booking (if policy allows) |
| POST | `/api/bookings/{id}/change-requests` | `{request_type: cancel\|reschedule, reason, proposed_start_date?, proposed_resource_id?}` |
| GET | `/api/me/dashboard` | Requester dashboard data |

### Calendar cell states

`available` (green), `limited` (yellow, which needs `activity_type_id`), `reserved` (blue, pending), `occupied`
(red, approved/completed), `non_working` (grey, with `reason` = `weekend|holiday|leave` and a `label` for holidays),
and `inactive` (grey). For requesters, cells include `bookings` only when `mine: true`.

### Availability check

```http
POST /api/availability/check
{"resource_id": "…", "activity_type_id": "…", "start_date": "2027-03-01", "additional_days": 0}
```
```json
{
  "available": false,
  "duration_days": 8, "start_date": "2027-03-01", "end_date": "2027-03-11",
  "work_dates": ["2027-03-01", "2027-03-02", "2027-03-04", "…"],
  "reason": "overlapping_booking",
  "message": "The selected resource is no longer available for the requested dates. Please select another resource or date.",
  "issues": [{"type": "overlapping_booking", "message": "…", "dates": ["2027-03-04"]}],
  "suggested_start_date": "2027-03-12",
  "alternative_resources": [{"id": "…", "display_name": "Resource 02"}]
}
```

### Submit booking

`BookingCreate` accepts **only**: `application_name, application_version, activity_type_id, pci_dss_scope,
resource_id, start_date, poc_name, poc_email, additional_comments?, additional_days?`. Any other field (`end_date`,
`duration_days`, `status`, `force`, …) is rejected with 422. The end date, duration, UUID v4 id and status
(`pending_approval`) come from the server. A 201 response returns the booking; a 409 `resource_unavailable` means
the slot was taken.

## Admin

### Bookings

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/calendar?start&end[&activity_type_id]` | Grid with engineer names, booking details, overlap flags, leave and booking list |
| GET | `/api/admin/bookings?status&resource_id&activity_type_id&q&start&end&needs_review&pci&limit&offset` | Search / filter |
| GET | `/api/admin/bookings/{id}` | Booking, status history, locks, audit, conflicts, change requests, emails |
| POST | `/api/admin/availability/check` | Like the requester check plus `exclude_booking_id`, booking ids and inactive resources |
| POST | `/api/admin/bookings` | Manual allocation: `BookingCreate` + `initial_status`, `duration_days?`, `end_date?`, `reason?`, `force?` |
| PATCH | `/api/admin/bookings/{id}` | Modify / reassign / reschedule: any of `resource_id, start_date, activity_type_id, additional_days, duration_days, end_date, recalculate, application_*, pci_dss_scope, poc_*, additional_comments`, plus **required** `reason` and optional `force` |
| POST | `/api/admin/bookings/{id}/approve` | `{force?}`. Revalidates. 409 `override_required` on conflict |
| POST | `/api/admin/bookings/{id}/reject` | `{reason}` (required) |
| POST | `/api/admin/bookings/{id}/cancel` | `{reason}` |
| GET | `/api/admin/change-requests?status` | Requester change requests |
| POST | `/api/admin/change-requests/{id}/decide` | `{approve, note?, force?}` (note required when declining) |
| POST | `/api/admin/jobs/run` | Run the expiry and completion sweeps now |

### Force Allocate

1. Send the request without `force`. If there is a conflict or restriction you get:
   ```json
   {"error": {"code": "override_required", "message": "…", "details": {
     "requires_force": true,
     "warning": "Warning: This allocation conflicts with an existing booking or resource restriction. …",
     "issues": [{"type": "overlapping_booking", "message": "…", "dates": ["…"], "booking_ids": ["…"]}],
     "conflicting_bookings": [{"id": "…", "application_name": "…", "status": "approved", "poc_email": "…"}],
     "plan": {"start_date": "…", "end_date": "…", "duration_days": 8, "work_dates": ["…"]}}}}
   ```
2. After showing the warning, resend the same request with `"force": {"confirm": true, "reason": "<mandatory>"}`.
   - A non-admin caller gets **403** (audited). A missing confirmation gets 422 `confirmation_required`; a blank
     reason gets 422 `override_reason_required`.

### Products

| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/admin/products` | List (with implementations and usage counts) / create `{name, description}` |
| PATCH/DELETE | `/api/admin/products/{id}` | Edit / (de)activate / delete (only when unused) |
| POST | `/api/admin/products/{id}/implementations` | Add an implementation |
| PATCH/DELETE | `/api/admin/implementations/{id}` | Edit / (de)activate / delete (only when unused) |

Users accept `product_id` / `implementation_id` on create and update. Bookings (admin create/modify) accept them too.
`GET /api/admin/bookings` filters by `product_id`, `implementation_id` and `requires_resource`. `POST /api/admin/bookings/{id}/complete`
completes an approved booking that has no resource. The dashboard accepts `product_id` and returns `product_distribution`,
`implementation_distribution` and `product_month_matrix`.

### Conflicts and audit

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/conflicts?status=open\|resolved&conflict_type&booking_id` | Conflict register |
| POST | `/api/admin/conflicts/{id}/resolve` | `{resolution_note}` |
| GET | `/api/admin/audit?booking_id&actor&action&entity_type&start&end&limit&offset` | Read-only audit log (no write endpoints exist) |

### Configuration

| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/admin/resources` | List / add (identifier auto-assigned) |
| DELETE | `/api/admin/resources/{id}` | Delete. 409 `resource_in_use` while it has pending/approved bookings (details list them). Never-booked resources are removed with their leave; otherwise archived (`mode: archived`) |
| GET | `/api/admin/resources?include_deleted=true` / POST `/api/admin/resources/{id}/restore` | Show / restore archived resources (restored as inactive) |
| PATCH | `/api/admin/resources/{id}` | Edit. Deactivate: `{"is_active": false}` (immediately) or `{"inactive_from": "YYYY-MM-DD"}` (from a date, today or later). `{"inactive_from": null}` cancels a scheduled deactivation; `{"is_active": true}` reactivates. Optional `reason`. The response lists flagged bookings |
| GET | `/api/admin/resources/{id}/allocation` | Engineer's bookings and leave |
| GET/POST | `/api/admin/activity-types` | List / add |
| PATCH | `/api/admin/activity-types/{id}` | Edit / (de)activate. Durations must be positive integers |
| GET/POST | `/api/admin/holidays[?year]` | List / add. Response includes `flagged_bookings` |
| PATCH/DELETE | `/api/admin/holidays/{id}` | Edit / delete (flags affected bookings) |
| POST | `/api/admin/holidays/import` | multipart `file` (.csv/.xlsx, columns `name,date,description`, ≤2 MB, ≤1000 rows) |
| GET/POST | `/api/admin/leaves` | List (`resource_id, start, end, include_cancelled`) / add |
| PATCH/DELETE | `/api/admin/leaves/{id}` | Edit / cancel (flags affected bookings) |
| GET/POST | `/api/admin/users[?include_deleted=true]`, PATCH `/api/admin/users/{id}` | User management |
| DELETE | `/api/admin/users/{id}` | Delete. Users with no activity are removed; users with history are archived (can't sign in, hidden, email reusable). Can't delete yourself or the last active admin |
| POST | `/api/admin/users/{id}/restore` | Restore an archived user (restored disabled) |
| GET/PUT | `/api/admin/settings` | `{values: {key: value}}`. Secrets are never accepted or returned |
| GET | `/api/admin/email-templates`, `/api/admin/email-templates/variables` | Templates and allowed variables |
| PUT | `/api/admin/email-templates/{key}` | Edit (unknown variables are rejected) |
| POST | `/api/admin/email-templates/{key}/preview` | Render with sample data |
| GET | `/api/admin/email-logs?status&booking_id&recipient` | Delivery log |
| POST | `/api/admin/email-logs/{id}/retry` | Requeue |

### Single sign-on administration

| Method | Path | Description |
|---|---|---|
| GET/PUT | `/api/admin/sso/settings` | `local_login_mode` (`all`/`admins_only`/`disabled`), `public_base_url`, `sso_auto_redirect` (with lockout safeguards) |
| GET | `/api/admin/sso/presets` | Defaults and set-up help for Entra ID, Okta, Google, Keycloak, Generic |
| GET/POST | `/api/admin/sso/providers` | List / create (created disabled). `client_secret` is write-only; responses expose `has_client_secret` and `redirect_uri` |
| GET/PATCH/DELETE | `/api/admin/sso/providers/{id}` | Edit (`client_secret` to replace, `clear_client_secret` to remove), enable/disable, delete (unlinks users) |
| GET | `/api/admin/sso/providers/{id}/recent-logins` | Last 25 SSO sign-ins/failures with groups received, matched groups, role changes and skip reasons |
| POST | `/api/admin/sso/providers/{id}/test` | Checks discovery, issuer, JWKS, algorithms, PKCE support, secret |

`POST /api/admin/users` accepts no `password` to create an SSO-only account. `PATCH /api/admin/users/{id}` also
accepts `remove_password` and `unlink_sso`.

### Reports

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/dashboard?start&end` | KPIs (today) + charts (range): monthly utilisation, activity distribution, status distribution, resource allocation, monthly volume |
| GET | `/api/admin/reports/bookings.csv` / `.xlsx` `?status&start&end&resource_id` | Export (formula-injection safe, audited) |
