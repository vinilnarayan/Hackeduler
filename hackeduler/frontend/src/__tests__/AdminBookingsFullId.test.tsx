import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import AdminBookings from '../pages/admin/Bookings'

const ID = 'fc514806-a073-45bd-8f92-1f5fb655c071'

describe('Admin bookings: booking id', () => {
  it('shows the whole booking id', async () => {
    api.get.mockReset()
    api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/bookings') ? { total: 1, items: [{ id: ID, application_name: 'App', application_version: '1', status: 'approved', activity_name: 'Web PT', start_date: '2027-09-01', end_date: '2027-09-10', requires_resource: true, resource_display_name: 'Resource 01', submitted_at: '2026-11-20T06:41:00Z', requester_email: 'a@b.c', requester_name: 'A', pci_dss_scope: true, report_shared: false }] } : []))
    render(<MemoryRouter><AdminBookings /></MemoryRouter>)
    expect(await screen.findByText(ID)).toBeTruthy()
  })
})
