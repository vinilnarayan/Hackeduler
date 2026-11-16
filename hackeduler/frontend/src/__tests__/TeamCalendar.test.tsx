import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, validationMessage: (e: any) => String(e?.message ?? e) }))

import TeamCalendar from '../pages/admin/TeamCalendar'

const entry = (n: number, extra = {}) => ({ booking_id: `b${n}`, resource_id: `r${n}`, resource_name: `Resource 0${n}`, engineer_name: `Eng ${n}`, application_name: `App${n}`, application_version: '1', activity_name: `Web PT ${n}`, status: 'approved', tentative: false, start_date: '2099-03-02', end_date: '2099-03-03', ...extra })
const cal = {
  month: '2099-03', today: '2099-03-02',
  resources: [{ id: 'r1', display_name: 'Resource 01', engineer_name: 'Eng 1', is_active: true }, { id: 'r2', display_name: 'Resource 02', engineer_name: 'Eng 2', is_active: true }],
  summary: { working_days: 20, booked_days: 2, leave_days: 1, holidays: 1 },
  days: [
    { date: '2099-03-01', in_month: true, weekend: false, holiday: 'Spring Fest', entries: [], leaves: [] },
    { date: '2099-03-02', in_month: true, weekend: false, holiday: null, entries: [entry(1), entry(2, { tentative: true, status: 'pending_approval' })], leaves: [{ leave_id: 'l1', resource_id: 'r2', resource_name: 'Resource 02', engineer_name: 'Eng 2', leave_type: 'Casual leave' }] },
  ],
}

describe('Team Calendar', () => {
  beforeEach(() => { api.get.mockReset(); api.get.mockResolvedValue(cal) })

  it('shows each resource\'s activity, leave and holidays on the day', async () => {
    render(<TeamCalendar />)
    expect(await screen.findByText('Spring Fest')).toBeInTheDocument()
    expect(screen.getByText('Web PT 1')).toBeInTheDocument()
    expect(screen.getByText('Web PT 2')).toBeInTheDocument()
    expect(screen.getByText('Activity days 2')).toBeInTheDocument()
  })

  it('opens the day with application, status and leave details', async () => {
    render(<TeamCalendar />)
    fireEvent.click(await screen.findByLabelText(/2099-03-02: 2 activities/))
    expect(await screen.findByText('App1 v1')).toBeInTheDocument()
    expect(screen.getByText('pending approval')).toBeInTheDocument()
    expect(screen.getByText('Casual leave')).toBeInTheDocument()
  })

  it('filters by resource and moves between months', async () => {
    render(<TeamCalendar />)
    await screen.findByText('Spring Fest')
    fireEvent.change(screen.getByLabelText('Resource'), { target: { value: 'r2' } })
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/api/admin/team-calendar?resource_id=r2'))
    fireEvent.click(screen.getByLabelText('Next month'))
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/api/admin/team-calendar?month=2099-04&resource_id=r2'))
  })
})
