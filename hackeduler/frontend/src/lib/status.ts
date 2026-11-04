import type { BookingStatus, CellState } from '../api/types'

export const STATUS_LABELS: Record<BookingStatus, string> = {
  pending_approval: 'Pending Approval',
  approved: 'Approved',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
  completed: 'Completed',
  expired: 'Expired',
}

/** Consistent status colours used everywhere in the app. */
export const STATUS_BADGE: Record<BookingStatus, string> = {
  pending_approval: 'bg-blue-100 text-blue-800 ring-blue-600/20',
  approved: 'bg-emerald-100 text-emerald-800 ring-emerald-600/20',
  rejected: 'bg-red-100 text-red-800 ring-red-600/20',
  cancelled: 'bg-slate-200 text-slate-700 ring-slate-500/20',
  completed: 'bg-violet-100 text-violet-800 ring-violet-600/20',
  expired: 'bg-amber-100 text-amber-800 ring-amber-600/20',
}

export const STATUS_CHART: Record<BookingStatus, string> = {
  pending_approval: '#2563eb',
  approved: '#059669',
  rejected: '#dc2626',
  cancelled: '#64748b',
  completed: '#7c3aed',
  expired: '#d97706',
}

/** Availability colour legend (requirement 6.1). */
export const CELL_STYLE: Record<CellState, { cls: string; label: string; meaning: string }> = {
  available: { cls: 'bg-emerald-500 hover:bg-emerald-600', label: 'Green', meaning: 'Available' },
  occupied: { cls: 'bg-red-500', label: 'Red', meaning: 'Occupied by an approved booking' },
  limited: { cls: 'bg-amber-400 hover:bg-amber-500', label: 'Yellow', meaning: 'Limited – free, but the selected activity would not fit from this day' },
  reserved: { cls: 'bg-blue-500', label: 'Blue', meaning: 'Temporarily reserved by a pending request' },
  non_working: { cls: 'bg-slate-300', label: 'Grey', meaning: 'Non-working day: weekend, holiday or resource leave' },
  inactive: { cls: 'bg-slate-400 bg-[repeating-linear-gradient(45deg,transparent,transparent_3px,rgba(255,255,255,.35)_3px,rgba(255,255,255,.35)_6px)]', label: 'Grey (hatched)', meaning: 'Inactive resource' },
}

export function cellExplanation(state: CellState, reason?: string, label?: string): string {
  if (state === 'non_working') {
    if (reason === 'weekend') return 'Weekend (non-working day)'
    if (reason === 'holiday') return `Organisation holiday${label ? `: ${label}` : ''}`
    if (reason === 'leave') return 'Resource unavailable (leave)'
  }
  if (state === 'inactive') return 'Resource inactive'
  return CELL_STYLE[state].meaning
}

export const CONFLICT_TYPE_LABELS: Record<string, string> = {
  overlapping_booking: 'Overlapping booking',
  leave: 'Leave',
  holiday: 'Holiday',
  inactive_resource: 'Inactive resource',
  manual_override: 'Manual override',
}
