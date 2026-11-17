import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
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
})
