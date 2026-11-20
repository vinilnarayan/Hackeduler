import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Me', role: 'requester', products: [], product_name: null } }) }))

import MyBookings from '../pages/requester/MyBookings'

const base = { application_version: '1', status: 'approved', requires_resource: true, report_shared: false, report_type: null, submitted_at: '2026-11-20T06:41:00Z', is_mine: true, requester_name: 'Me', product_name: null, implementation_name: 'Staff', duration_days: 8, pending_change_request: null }
const rows = [
  { ...base, id: '11111111-aaaa-4bbb-8ccc-000000000001', application_name: 'Alpha App', activity_name: 'Web PT', resource_display_name: 'Resource 01', start_date: '2027-09-01', end_date: '2027-09-10', pci_dss_scope: true },
  { ...base, id: '22222222-aaaa-4bbb-8ccc-000000000002', application_name: 'Beta App', activity_name: 'Mobile PT', resource_display_name: 'Resource 08', start_date: '2027-04-29', end_date: '2027-05-14', pci_dss_scope: false, status: 'pending_approval' },
]

describe('My bookings: PCI column and search', () => {
  beforeEach(() => { api.get.mockReset(); api.get.mockResolvedValue(rows) })

  it('shows PCI scope per booking', async () => {
    render(<MemoryRouter><MyBookings /></MemoryRouter>)
    await screen.findByText('Alpha App')
    expect(screen.getByText('PCI scope', { selector: 'th *, th' })).toBeTruthy()
    expect(screen.getAllByText('PCI').length).toBe(1)
    expect(screen.getAllByText('Not in scope').length).toBe(1)
  })

  it('searches every column', async () => {
    render(<MemoryRouter><MyBookings /></MemoryRouter>)
    await screen.findByText('Alpha App')
    const box = screen.getByLabelText('Search bookings')
    const only = (name: string, gone: string) => { expect(screen.getByText(name)).toBeTruthy(); expect(screen.queryByText(gone)).toBeNull() }
    fireEvent.change(box, { target: { value: 'pci' } }); only('Alpha App', 'Beta App')            // PCI scope
    fireEvent.change(box, { target: { value: 'resource 08' } }); only('Beta App', 'Alpha App')   // resource
    fireEvent.change(box, { target: { value: '22222222' } }); only('Beta App', 'Alpha App')      // booking id
    fireEvent.change(box, { target: { value: 'pending' } }); only('Beta App', 'Alpha App')       // status
    fireEvent.change(box, { target: { value: '2027-09' } }); only('Alpha App', 'Beta App')       // date
    fireEvent.change(box, { target: { value: 'MOBILE staff' } }); only('Beta App', 'Alpha App')  // case-insensitive, several words
    fireEvent.change(box, { target: { value: 'zzz' } })
    expect(screen.getByText('No bookings match your search')).toBeTruthy()
    // the search no longer narrows the request on the server
    expect(api.get.mock.calls.every((c) => !String(c[0]).includes('q='))).toBe(true)
  })
})
