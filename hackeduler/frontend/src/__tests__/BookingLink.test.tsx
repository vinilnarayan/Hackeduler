import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))
vi.mock('../components/AdminBookingModal', () => ({
  AdminBookingModal: ({ bookingId, onClose }: any) => <div role="dialog" aria-label="Booking details">Details of {bookingId}<button onClick={onClose}>Close details</button></div>,
}))

import Bookings from '../pages/admin/Bookings'

const Where = () => { const l = useLocation(); return <div data-testid="where">{l.pathname + l.search}</div> }
const listCalls = () => api.get.mock.calls.map((c) => c[0] as string).filter((u) => u.startsWith('/api/admin/bookings?'))

describe('Bookings page opened from a link', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/bookings?') ? { total: 0, items: [] } : []))
  })

  it('opens the booking in ?booking= and does not use it as a list filter', async () => {
    render(<MemoryRouter initialEntries={['/admin/bookings?booking=b-42']}><Bookings /><Where /></MemoryRouter>)
    expect(await screen.findByText('Details of b-42')).toBeInTheDocument()
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(0))
    expect(listCalls().every((u) => !u.includes('booking='))).toBe(true)
  })

  it('removes the booking from the address when the details are closed, keeping the filters', async () => {
    render(<MemoryRouter initialEntries={['/admin/bookings?status=approved&booking=b-42']}><Bookings /><Where /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Close details'))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/admin/bookings?status=approved'))
    expect(screen.queryByText('Details of b-42')).toBeNull()
  })
})
