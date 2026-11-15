import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, validationMessage: (e: any) => String(e?.message ?? e) }))

import { MyMonthCalendar, shiftMonth } from '../components/MyMonthCalendar'

const day = (date: string, state: string, extra: object = {}) => ({ date, in_month: true, state, booking_ids: [], holiday: null, leave: null, ...extra })
const cal = (month: string) => ({
  month, today: `${month}-03`,
  days: [day(`${month}-01`, 'booked', { booking_ids: ['b1'] }), day(`${month}-02`, 'leave', { leave: { id: 'l1', leave_type: 'Annual', reason: null } }), day(`${month}-03`, 'free'), day(`${month}-04`, 'weekend')],
  bookings: { b1: { id: 'b1', application_name: 'PayApp', application_version: '2', activity_name: 'Web PT', start_date: `${month}-01`, end_date: `${month}-01`, report_shared: false, report_type: null } },
  summary: { working_days: 3, booked: 1, leave: 1, free: 1, tentative: 0, holidays: 0, conflicts: 0 },
})

describe('MyMonthCalendar', () => {
  beforeEach(() => { api.get.mockReset(); api.get.mockImplementation((u: string) => Promise.resolve(cal(u.split('month=')[1] ?? '2027-03'))) })

  it('shows activity, leave and free days with the summary', async () => {
    render(<MemoryRouter><MyMonthCalendar /></MemoryRouter>)
    expect(await screen.findByText('PayApp')).toBeInTheDocument()
    expect(screen.getByText('Assigned 1 d')).toBeInTheDocument()
    expect(screen.getByText('Free 1 d')).toBeInTheDocument()
    expect(screen.getByText('Leave 1 d')).toBeInTheDocument()
    expect(screen.getAllByRole('gridcell').map((c) => c.getAttribute('data-state'))).toEqual(['booked', 'leave', 'free', 'weekend'])
  })

  it('navigates months and back to today', async () => {
    render(<MemoryRouter><MyMonthCalendar /></MemoryRouter>)
    await screen.findByText('PayApp')
    fireEvent.click(screen.getByLabelText('Next month'))
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/api/resource/calendar?month=2027-04'))
    fireEvent.click(screen.getByText('Today'))
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/api/resource/calendar'))
  })

  it('shifts across year boundaries', () => {
    expect(shiftMonth('2027-01', -1)).toBe('2026-12')
    expect(shiftMonth('2026-12', 1)).toBe('2027-01')
  })
})
