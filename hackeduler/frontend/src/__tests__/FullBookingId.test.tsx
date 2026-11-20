import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Me', role: 'requester' } }) }))

import MyBookings from '../pages/requester/MyBookings'

const ID = '10b146c5-1a2b-4c3d-8e9f-0123456789ab'

describe('My bookings: booking id', () => {
  it('shows the whole booking id', async () => {
    api.get.mockReset()
    api.get.mockResolvedValue([{ id: ID, application_name: 'iFlyCorporate Product', application_version: '1', status: 'approved', activity_name: 'Web Application PT', start_date: '2027-09-01', end_date: '2027-09-10', requires_resource: true, resource_display_name: 'Resource 06', submitted_at: '2026-11-20T06:41:00Z', requester_name: 'Me', report_shared: false }])
    render(<MemoryRouter><MyBookings /></MemoryRouter>)
    expect(await screen.findByText(ID)).toBeTruthy()
  })
})
