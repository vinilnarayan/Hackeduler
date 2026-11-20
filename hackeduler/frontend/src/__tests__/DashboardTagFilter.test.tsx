import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import Dashboard from '../pages/admin/Dashboard'

const products = [{ id: 'p1', name: 'Alpha', tags: ['Payments'], is_active: true, implementations: [{ id: 'i1', tags: ['SaaS', 'payments'] }] }]
const kpis = Object.fromEntries(['total_resources', 'active_resources', 'available_today', 'occupied_today', 'reserved_today', 'on_leave_today', 'pending_requests', 'approved', 'rejected', 'cancelled', 'completed', 'expired', 'unresolved_conflicts', 'utilization_pct', 'bookings_without_resource', 'bookings_in_range', 'pci_bookings', 'non_pci_bookings', 'reports_shared'].map((k) => [k, 0]))
const dash = {
  range: { start: '2026-06-01', end: '2027-03-31' }, today: '2026-11-20', kpis, engineers_on_leave_today: [], upcoming_bookings: [], pending_bookings: [], upcoming_holidays: [],
  charts: { monthly_utilization: [], activity_distribution: [], status_distribution: [], resource_allocation: [], monthly_volume: [], product_distribution: [], product_month_matrix: { months: [], rows: [] }, implementation_distribution: [] },
}

describe('Admin dashboard: tag filter', () => {
  it('lists the tags in use (product and implementation, no duplicates) and sends the chosen one', async () => {
    api.get.mockReset()
    api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/products') ? products : dash))
    render(<MemoryRouter><Dashboard /></MemoryRouter>)
    const sel = (await screen.findByLabelText('Tag')) as HTMLSelectElement
    expect(Array.from(sel.options).map((o) => o.text)).toEqual(['All tags', 'Payments', 'SaaS'])
    fireEvent.change(sel, { target: { value: 'SaaS' } })
    await vi.waitFor(() => expect(api.get.mock.calls.some((c) => String(c[0]).startsWith('/api/admin/dashboard') && String(c[0]).includes('tag=SaaS'))).toBe(true))
  })
})
