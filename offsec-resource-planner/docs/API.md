# REST API

Interactive OpenAPI documentation is served at **`/api/docs`** (Swagger UI) and `/api/redoc`. The machine-readable
schema is at `/api/openapi.json`.

## Conventions

- **Auth:** `POST /api/auth/login` sets an HttpOnly session cookie (`orp_session`) and a CSRF cookie (`orp_csrf`).
  Every `POST/PUT/PATCH/DELETE` must send `X-CSRF-Token: <value of orp_csrf>`.
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
| GET | `/api/auth/sso/{slug}/login[?next=/path]` | 302 to the IdP (sets the encrypted `orp_sso_tx` cookie) |
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
| POST | `/api/availability/check` | Server-side slot calculation |
| POST | `/api/bookings` | Submit booking |
| GET | `/api/bookings/mine?status&q` | Own bookings |
| GET | `/api/bookings/{id}` | Own booking (404 otherwise) |
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
| PATCH | `/api/admin/resources/{id}` | Edit, `is_active` toggle (+`reason`) |
| GET | `/api/admin/resources/{id}/allocation` | Engineer's bookings and leave |
| GET/POST | `/api/admin/activity-types` | List / add |
| PATCH | `/api/admin/activity-types/{id}` | Edit / (de)activate. Durations must be positive integers |
| GET/POST | `/api/admin/holidays[?year]` | List / add. Response includes `flagged_bookings` |
| PATCH/DELETE | `/api/admin/holidays/{id}` | Edit / delete (flags affected bookings) |
| POST | `/api/admin/holidays/import` | multipart `file` (.csv/.xlsx, columns `name,date,description`, ≤2 MB, ≤1000 rows) |
| GET/POST | `/api/admin/leaves` | List (`resource_id, start, end, include_cancelled`) / add |
| PATCH/DELETE | `/api/admin/leaves/{id}` | Edit / cancel (flags affected bookings) |
| GET/POST | `/api/admin/users`, PATCH `/api/admin/users/{id}` | User management |
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
| POST | `/api/admin/sso/providers/{id}/test` | Checks discovery, issuer, JWKS, algorithms, PKCE support, secret |

`POST /api/admin/users` accepts no `password` to create an SSO-only account. `PATCH /api/admin/users/{id}` also
accepts `remove_password` and `unlink_sso`.

### Reports

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/dashboard?start&end` | KPIs (today) + charts (range): monthly utilisation, activity distribution, status distribution, resource allocation, monthly volume |
| GET | `/api/admin/reports/bookings.csv` / `.xlsx` `?status&start&end&resource_id` | Export (formula-injection safe, audited) |
