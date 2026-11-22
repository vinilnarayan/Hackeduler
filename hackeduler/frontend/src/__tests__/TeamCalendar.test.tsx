import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
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
    { date: '2099-03-01', in_month: true, weekend: false, holiday: 'Spring Fest', entries: [], leaves: [], free: [] },
    { date: '2099-03-02', in_month: true, weekend: false, holiday: null, entries: [entry(1), entry(2, { tentative: true, status: 'pending_approval' })], leaves: [{ leave_id: 'l1', resource_id: 'r2', resource_name: 'Resource 02', engineer_name: 'Eng 2', leave_type: 'Casual leave' }],
      free: [{ resource_id: 'r3', resource_name: 'Resource 03', engineer_name: 'Eng 3' }] },
    { date: '2099-03-06', in_month: true, weekend: true, holiday: null, entries: [], leaves: [], free: [] },
  ],
}

describe('Team Calendar', () => {
  beforeEach(() => { api.get.mockReset(); api.get.mockResolvedValue(cal) })

  it('shows each resource\'s activity, leave and holidays on the day', async () => {
    render(<MemoryRouter><TeamCalendar /></MemoryRouter>)
    expect(await screen.findByText('Spring Fest')).toBeInTheDocument()
    // each cell: engineer initials + application name + version (not the resource number / activity type)
    const cell = (app: string) => screen.getByText((_, el) => el?.tagName === 'SPAN' && el.className.includes('truncate') && (el.textContent ?? '').includes(app))
    expect(cell('App1 v1').textContent).toBe('E1 App1 v1')
    expect(cell('App2 v1').textContent).toBe('E2 App2 v1')
    expect(screen.queryByText('R01')).toBeNull()
    // each booking has its own colour
    expect(cell('App1 v1').style.backgroundColor).not.toBe('')
    expect(cell('App1 v1').style.backgroundColor).not.toBe(cell('App2 v1').style.backgroundColor)
    expect(screen.getByText('Activity days 2')).toBeInTheDocument()
  })

  it('opens the day with application, status and leave details', async () => {
    render(<MemoryRouter><TeamCalendar /></MemoryRouter>)
    fireEvent.click(await screen.findByLabelText(/2099-03-02: 2 activities/))
    const link = await screen.findByRole('link', { name: /App1 v1/ })
    expect(link).toHaveAttribute('href', '/admin/bookings?booking=b1')       // opens that booking's details on the Bookings page
    expect(screen.getByRole('link', { name: /App2 v1/ })).toHaveAttribute('href', '/admin/bookings?booking=b2')
    expect(screen.getByText('pending approval')).toBeInTheDocument()
    expect(screen.getByText('Casual leave')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Free (1)' })).toBeInTheDocument()
    expect(screen.getByText('Eng 3', { selector: 'span.rounded' })).toBeInTheDocument()
    expect(screen.queryByText(/Resource 0\d/, { selector: 'span.rounded' })).toBeNull()     // engineer names, not resource names
  })

  it('says nobody is scheduled on a non-working day instead of listing free resources', async () => {
    render(<MemoryRouter><TeamCalendar /></MemoryRouter>)
    fireEvent.click(await screen.findByLabelText(/2099-03-06/))
    expect(await screen.findByText(/Non-working day – nobody is scheduled/)).toBeInTheDocument()
  })

  it('filters by resource and moves between months', async () => {
    render(<MemoryRouter><TeamCalendar /></MemoryRouter>)
    await screen.findByText('Spring Fest')
    fireEvent.change(screen.getByLabelText('Engineer'), { target: { value: 'r2' } })
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/api/admin/team-calendar?resource_id=r2'))
    fireEvent.click(screen.getByLabelText('Next month'))
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/api/admin/team-calendar?month=2099-04&resource_id=r2'))
  })

  describe('week view', () => {
    const week = {
      ...cal, month: '2099-03', week: '2099-03-02', summary: { working_days: 5, booked_days: 2, leave_days: 1, holidays: 0 },
      days: ['02', '03', '04', '05', '06', '07', '08'].map((dd, i) => ({
        date: `2099-03-${dd}`, in_month: true, weekend: i > 4, holiday: null,
        entries: dd === '02' ? [entry(1), entry(2, { tentative: true, status: 'pending_approval' })] : [],
        leaves: dd === '02' ? [{ leave_id: 'l1', resource_id: 'r2', resource_name: 'Resource 02', engineer_name: 'Eng 2', leave_type: 'Casual leave' }] : [],
        free: i > 4 || dd === '02' ? [] : [{ resource_id: 'r1', resource_name: 'Resource 01', engineer_name: 'Eng 1' }],
      })),
    }
    beforeEach(() => { api.get.mockImplementation((u: string) => Promise.resolve(u.includes('week=') ? week : cal)) })

    it('switches to the week view and back, asking the server for that week', async () => {
      render(<MemoryRouter><TeamCalendar /></MemoryRouter>)
      await screen.findByText('Spring Fest')
      fireEvent.click(screen.getByRole('button', { name: 'Week' }))
      await waitFor(() => expect(api.get.mock.calls.some((c) => /\?week=\d{4}-\d{2}-\d{2}$/.test(String(c[0])))).toBe(true))
      expect(await screen.findByText('2 Mar – 8 Mar 2099')).toBeInTheDocument()
      expect(screen.getByLabelText('Next week')).toBeInTheDocument()
      fireEvent.click(screen.getByLabelText('Next week'))
      await waitFor(() => expect(api.get.mock.calls.some((c) => String(c[0]).includes('week=') && !String(c[0]).includes(week.week))).toBe(true))
      fireEvent.click(screen.getByRole('button', { name: 'Month' }))
      expect(await screen.findByLabelText('Next month')).toBeInTheDocument()
    })

    it('by day: lists every booking in full with the engineer name, no "+N more"', async () => {
      render(<MemoryRouter><TeamCalendar /></MemoryRouter>)
      fireEvent.click(await screen.findByRole('button', { name: 'Week' }))
      await screen.findByText('2 Mar – 8 Mar 2099')
      expect(screen.getByText('Web PT 1 · Eng 1')).toBeInTheDocument()
      expect(screen.getByText('Web PT 2 · Eng 2')).toBeInTheDocument()
      expect(screen.getByText(/Eng 2 on leave/)).toBeInTheDocument()
      expect(screen.queryByText(/more/)).toBeNull()
      expect(screen.queryByText(/Resource 0\d/)).toBeNull()
      fireEvent.click(screen.getByLabelText(/2099-03-02: 2 activities/))
      expect(await screen.findByRole('link', { name: /App1 v1/ })).toHaveAttribute('href', '/admin/bookings?booking=b1')
    })

    it('by engineer: one row per engineer, with Free, Leave and the application per day', async () => {
      render(<MemoryRouter><TeamCalendar /></MemoryRouter>)
      fireEvent.click(await screen.findByRole('button', { name: 'Week' }))
      fireEvent.click(await screen.findByRole('button', { name: 'By engineer' }))
      expect(await screen.findByRole('rowheader', { name: 'Eng 1' })).toBeInTheDocument()
      expect(screen.getByRole('rowheader', { name: 'Eng 2' })).toBeInTheDocument()
      expect(screen.getByLabelText('Eng 1 2099-03-02').textContent).toContain('App1 v1')
      expect(screen.getByLabelText('Eng 2 2099-03-02').textContent).toContain('Leave')
      expect(screen.getByLabelText('Eng 1 2099-03-03').textContent).toContain('Free')
      fireEvent.change(screen.getByLabelText('Engineer'), { target: { value: 'r2' } })
      await waitFor(() => expect(screen.queryByRole('rowheader', { name: 'Eng 1' })).toBeNull())
    })
  })
})
