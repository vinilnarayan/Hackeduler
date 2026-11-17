import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import ManualAllocation from '../pages/admin/ManualAllocation'

const act = { id: 'a1', name: 'Others', is_active: true, base_duration_days: 1, requires_resource: true, description: '' }
const range = {
  start_date: '2027-03-01', end_date: '2027-03-08', calendar_days: 8, working_days: 4, work_dates: [],
  skipped: { weekend: 2, holiday: 1, leave: 1 }, leave_considered: true, available: true, issues: [], message: '',
  skipped_dates: [{ date: '2027-03-03', reason: 'holiday', label: 'Spring Fest' }, { date: '2027-03-04', reason: 'leave', label: null }],
}
const std = { available: true, start_date: '2027-03-01', end_date: '2027-03-01', duration_days: 1, issues: [], message: '' }

describe('Manual allocation: actual range', () => {
  beforeEach(() => {
    api.get.mockReset(); api.post.mockReset()
    api.get.mockImplementation((u: string) => Promise.resolve(u.includes('activity-types') ? [act] : []))
    api.post.mockImplementation((u: string) => Promise.resolve(u.includes('/range') ? range : std))
  })

  it('shows the standard calculation and the actual working days for the chosen end date', async () => {
    render(<MemoryRouter initialEntries={['/?start=2027-03-01']}><ManualAllocation /></MemoryRouter>)
    fireEvent.change(await screen.findByLabelText(/Activity type/), { target: { value: 'a1' } })
    fireEvent.change(screen.getByLabelText(/End date/), { target: { value: '2027-03-08' } })
    const box = await screen.findByTestId('actual-range')
    expect(box.textContent).toMatch(/4 working days of 8 calendar days/)
    expect(box.textContent).toMatch(/2 weekend days, 1 holiday, 1 leave day/)
    expect(box.textContent).toMatch(/Spring Fest/)
    expect(await screen.findByText(/Standard calculation/)).toBeTruthy()
    expect(screen.getByText(/1 working day\)/)).toBeTruthy()
  })

  it('shows no actual box without an end date', async () => {
    render(<MemoryRouter initialEntries={['/?start=2027-03-01']}><ManualAllocation /></MemoryRouter>)
    await screen.findByLabelText(/Activity type/)
    expect(screen.queryByTestId('actual-range')).toBeNull()
  })
})
