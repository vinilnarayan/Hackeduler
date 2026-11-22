import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', full_name: 'Asha Rao', role: 'resource' } }) }))
vi.mock('../api/client', () => ({ ...api, validationMessage: (e: any) => String(e?.message ?? e) }))

import { MyMonthCalendar, shiftMonth } from '../components/MyMonthCalendar'

const day = (date: string, state: string, extra: object = {}) => ({ date, in_month: true, state, booking_ids: [], holiday: null, leave: null, notes: [], ...extra })
const cal = (month: string) => ({
  month, today: `${month}-03`,
  days: [day(`${month}-01`, 'booked', { booking_ids: ['b1'] }), day(`${month}-02`, 'leave', { leave: { id: 'l1', leave_type: 'Annual', reason: null } }), day(`${month}-03`, 'free', { notes: [{ id: 'n1', note: 'Call client' }] }), day(`${month}-04`, 'weekend')],
  bookings: { b1: { id: 'b1', application_name: 'PayApp', application_version: '2', activity_name: 'Web PT', start_date: `${month}-01`, end_date: `${month}-01`, report_shared: false, report_type: null } },
  leave_types: ['Annual leave', 'Casual leave', 'Personal leave'], personal_leave: { year: 2099, limit: 2, used: 1 },
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

  it('shows notes on the day and opens a dialog with notes and leave forms on click', async () => {
    render(<MemoryRouter><MyMonthCalendar /></MemoryRouter>)
    fireEvent.click(await screen.findByText(/Call client/))
    expect(await screen.findByLabelText('Add a note')).toBeInTheDocument()
    expect(screen.getByText('Call client', { selector: 'p' })).toBeInTheDocument()
    const types = Array.from((screen.getByLabelText('Leave type') as HTMLSelectElement).options).map((o) => o.value)
    expect(types).toEqual(['Annual leave', 'Casual leave', 'Personal leave'])
  })

  it('saves a note and a leave for the clicked day, then reloads', async () => {
    api.post.mockResolvedValue({ overlapping_bookings: 0 })
    render(<MemoryRouter><MyMonthCalendar /></MemoryRouter>)
    fireEvent.click(await screen.findByLabelText(/-03: free/))
    fireEvent.change(await screen.findByLabelText('Add a note'), { target: { value: 'Prep demo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add note' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/resource/notes', { note_date: expect.stringMatching(/-03$/), note: 'Prep demo' }))
    fireEvent.change(screen.getByLabelText('Leave type'), { target: { value: 'Personal leave' } })
    expect(screen.getByText(/1 of 2 days used in 2099 \(1 left\)/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Comment'), { target: { value: 'Family event' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save leave' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/resource/leaves', { start_date: expect.stringMatching(/-03$/), end_date: expect.stringMatching(/-03$/), leave_type: 'Personal leave', reason: 'Family event' }))
    await waitFor(() => expect(api.get.mock.calls.length).toBeGreaterThan(2))
  })

  it('cancels existing leave from its day', async () => {
    api.del.mockResolvedValue({ ok: true })
    api.get.mockImplementation(() => Promise.resolve({ ...cal('2099-03'), days: [day('2099-03-02', 'leave', { leave: { id: 'l1', leave_type: 'Annual leave', reason: null, start_date: '2099-03-02', end_date: '2099-03-02' } })] }))
    render(<MemoryRouter><MyMonthCalendar /></MemoryRouter>)
    fireEvent.click(await screen.findByLabelText(/2099-03-02: leave/))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel this leave' }))
    await waitFor(() => expect(api.del).toHaveBeenCalledWith('/api/resource/leaves/l1'))
  })

  describe('week view and own timeline', () => {
    const week = (u: string) => {
      const mon = u.split('week=')[1]
      const dd = (n: number) => { const d = new Date(`${mon}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
      return {
        month: '2099-03', week: mon, today: dd(0),
        days: [
          { ...day(dd(0), 'booked', { booking_ids: ['b1'] }) }, { ...day(dd(1), 'booked', { booking_ids: ['b1'] }) },
          day(dd(2), 'leave', { leave: { id: 'l1', leave_type: 'Annual', reason: null } }), day(dd(3), 'leave', { leave: { id: 'l1', leave_type: 'Annual', reason: null } }),
          day(dd(4), 'free'), day(dd(5), 'weekend'), day(dd(6), 'weekend'),
        ],
        bookings: { b1: { id: 'b1', application_name: 'PayApp', application_version: '2', activity_name: 'Web PT', start_date: dd(0), end_date: dd(1), report_shared: false, report_type: null } },
        leave_types: [], personal_leave: { year: 2099, limit: 2, used: 0 }, summary: { working_days: 5, booked: 2, leave: 2, free: 1, tentative: 0, holidays: 0, conflicts: 0 },
      }
    }
    beforeEach(() => { api.get.mockImplementation((u: string) => Promise.resolve(u.includes('week=') ? week(u) : cal(u.split('month=')[1] ?? '2027-03'))) })

    it('switches to a week (asking the server for that week), moves by week, and back to month', async () => {
      render(<MemoryRouter><MyMonthCalendar /></MemoryRouter>)
      await screen.findByText('PayApp')
      fireEvent.click(screen.getByRole('button', { name: 'Week' }))
      await waitFor(() => expect(api.get.mock.calls.some((c) => /\/api\/resource\/calendar\?week=\d{4}-\d{2}-\d{2}$/.test(String(c[0])))).toBe(true))
      expect(await screen.findByLabelText('Next week')).toBeInTheDocument()
      expect(await screen.findAllByRole('gridcell')).toHaveLength(7)
      fireEvent.click(screen.getByLabelText('Next week'))
      await waitFor(() => expect(api.get.mock.calls.filter((c) => String(c[0]).includes('week=')).length).toBeGreaterThan(1))
      fireEvent.click(screen.getByRole('button', { name: 'Month' }))
      expect(await screen.findByLabelText('Next month')).toBeInTheDocument()
    })

    it('By engineer shows only my own row, with one bar per booking and per leave', async () => {
      render(<MemoryRouter><MyMonthCalendar /></MemoryRouter>)
      await screen.findByText('PayApp')
      fireEvent.click(screen.getByRole('button', { name: 'Week' }))
      await screen.findByLabelText('Next week')
      fireEvent.click(screen.getByRole('button', { name: 'By engineer' }))
      expect(await screen.findByRole('rowheader', { name: 'Asha Rao' })).toBeInTheDocument()
      expect(screen.getAllByRole('rowheader')).toHaveLength(1)
      const bar = screen.getByRole('button', { name: /PayApp v2/ })
      expect(bar.closest('td')).toHaveAttribute('colspan', '2')                     // two booked days, one bar
      expect(screen.getByText(/Leave · Annual/).closest('td')).toHaveAttribute('colspan', '2')
      expect(screen.getByText('Free', { selector: 'td span' })).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'By day' }))
      expect(await screen.findAllByRole('gridcell')).toHaveLength(7)
    })
  })
})
