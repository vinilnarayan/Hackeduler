export type Role = 'admin' | 'requester'
export type BookingStatus = 'pending_approval' | 'approved' | 'rejected' | 'cancelled' | 'completed' | 'expired'

export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  last_login_at?: string | null
  has_password?: boolean
  sso_provider_id?: string | null
  sso_provider_name?: string | null
  last_login_method?: string | null
  deleted_at?: string | null
  product_id?: string | null
  product_name?: string | null
  implementation_id?: string | null
  implementation_name?: string | null
}

export interface Implementation { id: string; product_id: string; name: string; description: string | null; is_active: boolean; users: number; bookings: number }
export interface Product { id: string; name: string; description: string | null; is_active: boolean; users: number; bookings: number; implementations: Implementation[] }

export interface SSOProvider {
  id: string
  slug: string
  display_name: string
  provider_type: 'entra' | 'okta' | 'google' | 'keycloak' | 'generic'
  enabled: boolean
  sort_order: number
  issuer: string
  discovery_url: string | null
  authorization_endpoint: string | null
  token_endpoint: string | null
  jwks_uri: string | null
  userinfo_endpoint: string | null
  end_session_endpoint: string | null
  client_id: string
  has_client_secret: boolean
  token_auth_method: 'client_secret_post' | 'client_secret_basic' | 'none'
  scopes: string
  extra_auth_params: Record<string, string>
  use_pkce: boolean
  fetch_userinfo: boolean
  rp_initiated_logout: boolean
  email_claim: string
  name_claim: string
  groups_claim: string
  admin_groups: string[]
  requester_groups: string[]
  allowed_email_domains: string[]
  auto_provision: boolean
  default_role: 'requester' | 'admin'
  sync_role_on_login: boolean
  link_existing_by_email: boolean
  clock_skew_seconds: number
  redirect_uri: string
  last_tested_at: string | null
  last_test_ok: boolean | null
  linked_users: number
}

export interface ResourcePublic {
  id: string
  code: string
  display_name: string
  is_active: boolean
}

export interface ResourceAdmin extends ResourcePublic {
  sequence_no: number
  engineer_name: string
  engineer_email: string | null
  notes: string | null
  visible_to_requesters?: boolean
  deactivated_at: string | null
  inactive_from: string | null
  inactive_reason: string | null
  deleted_at?: string | null
  created_at: string
}

export interface ActivityType {
  id: string
  name: string
  description: string | null
  base_duration_days: number | null
  requires_resource: boolean
  allow_additional_days: boolean
  max_additional_days: number
  is_active: boolean
  sort_order: number
  visible_to_requesters: boolean
  deleted_at: string | null
  initiation_email_enabled?: boolean
  initiation_days_before?: number | null
  initiation_details?: string | null
  initiation_details_default?: string | null
}

export interface Holiday {
  id: string
  name: string
  holiday_date: string
  description: string | null
}

export interface Leave {
  id: string
  resource_id: string
  resource_code: string
  resource_display_name: string
  engineer_name: string
  start_date: string
  end_date: string
  leave_type: string | null
  reason: string | null
  status: string
}

export interface Booking {
  id: string
  application_name: string
  application_version: string
  activity_type_id: string
  activity_name: string
  duration_days: number | null
  additional_days: number
  pci_dss_scope: boolean
  requires_resource: boolean
  resource_id: string | null
  resource_display_name: string | null
  start_date: string | null
  end_date: string | null
  product_id: string | null
  product_name: string | null
  implementation_id: string | null
  implementation_name: string | null
  is_mine: boolean
  requester_name: string | null
  poc_name: string
  poc_email: string
  additional_comments: string | null
  status: BookingStatus
  status_label: string
  submitted_at: string
  expires_at: string | null
  rejection_reason: string | null
  cancellation_reason: string | null
  pending_change_request: any | null
}

export interface AdminBooking extends Booking {
  resource_code: string | null
  engineer_name: string | null
  initiation_email_sent_at?: string | null
  initiation_email?: { state: 'sent' | 'scheduled' | 'disabled' | 'not_applicable'; sent_at: string | null; scheduled_for: string | null; days_before: number | null; can_send: boolean; note?: string } | null
  extra_resources: { id: string; code: string; display_name: string; engineer_name: string }[]
  requester_id: string
  requester_email: string
  source: string
  is_force_allocated: boolean
  needs_review: boolean
  duration_overridden: boolean
  base_duration_snapshot: number | null
  approved_at: string | null
  rejected_at: string | null
  cancelled_at: string | null
  version: number
  open_conflicts: number
}

export type CellState = 'available' | 'limited' | 'reserved' | 'occupied' | 'non_working' | 'inactive'

export interface CalendarCell {
  date: string
  state: CellState
  reason?: 'weekend' | 'holiday' | 'leave' | 'inactive'
  label?: string
  mine?: boolean
  team?: boolean
  conflict?: boolean
  bookings?: { id: string; status: BookingStatus; application_name: string; activity?: string; forced?: boolean }[]
}

export interface CalendarResource {
  id: string
  code: string
  display_name: string
  is_active: boolean
  inactive_from?: string | null
  engineer_name?: string
  days: CalendarCell[]
}

export interface CalendarGrid {
  start: string
  end: string
  holidays: { date: string; name: string }[]
  resources: CalendarResource[]
  leaves?: { id: string; resource_id: string; start_date: string; end_date: string; leave_type: string | null; reason: string | null }[]
  bookings?: AdminBooking[]
  open_conflicts?: number
}

export interface Issue {
  type: string
  message: string
  dates: string[]
  booking_ids?: string[]
}

export interface AvailabilityResult {
  available: boolean
  resource_id: string
  resource_display_name: string
  activity_type_id: string
  activity_name: string
  duration_days: number
  start_date: string
  end_date: string | null
  work_dates: string[]
  issues: Issue[]
  reason: string | null
  message: string
  suggested_start_date: string | null
  alternative_resources: { id: string; display_name: string }[]
}

export interface ForcePayload {
  confirm: boolean
  reason: string
}

export interface OverrideDetails {
  requires_force: boolean
  warning: string
  issues: Issue[]
  conflicting_bookings: { id: string; application_name: string; status: string; start_date: string; end_date: string; poc_name: string; poc_email: string }[]
  plan: { resource_id: string; start_date: string; end_date: string | null; duration_days: number; work_dates: string[] }
}

export interface Conflict {
  id: string
  booking_id: string
  conflicting_booking_id: string | null
  resource_display_name: string | null
  engineer_name: string | null
  application_name: string
  booking_status: BookingStatus
  booking_start_date: string
  booking_end_date: string
  conflicting_application_name: string | null
  conflicting_booking_status: BookingStatus | null
  conflicting_start_date: string | null
  conflicting_end_date: string | null
  conflict_type: string
  description: string
  conflict_start_date: string | null
  conflict_end_date: string | null
  status: 'open' | 'resolved'
  resolution_note: string | null
  resolved_by_email?: string | null
  resolved_at: string | null
  created_at: string
}

export interface AuditEntry {
  id: string
  booking_id: string | null
  entity_type: string
  entity_id: string | null
  action: string
  previous_value: any
  new_value: any
  actor_email: string | null
  actor_role: string | null
  reason: string | null
  request_id: string | null
  ip_address: string | null
  created_at: string
}
