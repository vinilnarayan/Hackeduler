import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))

import NewBooking from '../pages/requester/NewBooking'

const acts = [
  { id: 'a1', name: 'XBOW', description: null, base_duration_days: null, requires_resource: false, allow_additional_days: false, max_additional_days: 0, is_active: true, sort_order: 0, visible_to_requesters: true, deleted_at: null, yearly_limit: 10, quota: { year: 2026, limit: 10, used: 1, remaining: 9 } },
  { id: 'a2', name: 'Scan', description: null, base_duration_days: null, requires_resource: false, allow_additional_days: false, max_additional_days: 0, is_active: true, sort_order: 1, visible_to_requesters: true, deleted_at: null, yearly_limit: null, quota: null },
]

describe('New booking: yearly balance', () => {
  beforeEach(() => {
    api.get.mockReset(); api.post.mockReset()
    api.get.mockImplementation((u: string) => Promise.resolve(u.includes('/api/me/implementations') ? { product: null, implementations: [], default_implementation_id: null, products: [] } : u.includes('/api/activity-types') ? acts : []))
    api.post.mockResolvedValue({ available: true, requires_resource: false, message: 'ok', duration_days: null, start_date: '2027-03-01', end_date: null, work_dates: [], reason: null, suggested_start_date: null, available_resources: 0, resource_display_name: null, quota: { year: 2027, limit: 10, used: 0, remaining: 10 } })
  })

  it('shows the balance on selecting a limited activity, and follows the start year', async () => {
    render(<MemoryRouter><NewBooking /></MemoryRouter>)
    const sel = await screen.findByLabelText(/Activity type/)
    expect(screen.queryByTestId('yearly-balance')).toBeNull()
    fireEvent.change(sel, { target: { value: 'a1' } })
    expect((await screen.findByTestId('yearly-balance')).textContent).toMatch(/Balance for 2026:\s*9\s*of 10/)
    fireEvent.change(screen.getByLabelText(/Preferred date/), { target: { value: '2027-03-01' } })
    await vi.waitFor(() => expect(screen.getByTestId('yearly-balance').textContent).toMatch(/Balance for 2027:\s*10\s*of 10/))
  })

  it('shows nothing for an unlimited activity', async () => {
    render(<MemoryRouter><NewBooking /></MemoryRouter>)
    fireEvent.change(await screen.findByLabelText(/Activity type/), { target: { value: 'a2' } })
    await vi.waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(screen.queryByTestId('yearly-balance')).toBeNull()
  })
})
