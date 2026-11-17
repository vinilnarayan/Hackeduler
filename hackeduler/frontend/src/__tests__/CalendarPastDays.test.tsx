import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, qs: (o: Record<string, string>) => '?' + new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString(), validationMessage: String }))

import { ResourceCalendar } from '../components/ResourceCalendar'

const cell = (date: string, state: string, extra: object = {}) => ({ date, state, ...extra })
const grid = {
  start: '2099-03-01', end: '2099-03-03', holidays: [],
  resources: [{ id: 'r1', code: 'R1', display_name: 'Resource 01', is_active: true, inactive_from: null, days: [
    cell('2099-03-01', 'available', { past: true }), cell('2099-03-02', 'limited', { past: true }), cell('2099-03-03', 'available'),
  ] }],
}

describe('Calendar: past days', () => {
  beforeEach(() => { api.get.mockReset(); api.get.mockResolvedValue(grid) })

  it('warns instead of booking when a past available day is clicked', async () => {
    const onCell = vi.fn()
    render(<ResourceCalendar mode="requester" onCellClick={onCell} />)
    fireEvent.click(await screen.findByLabelText(/Resource 01 · Sun 01 Mar 2099/))
    expect(await screen.findByText(/cannot be made for a past day/)).toBeInTheDocument()
    expect(onCell).not.toHaveBeenCalled()
  })

  it('warns for a past day that failed the fit check too, and says so in the tooltip', async () => {
    const onCell = vi.fn()
    render(<ResourceCalendar mode="admin" onCellClick={onCell} />)
    const c = await screen.findByLabelText(/Mon 02 Mar 2099/)
    expect(c.getAttribute('aria-label')).toContain('Past date – cannot be booked')
    fireEvent.click(c)
    expect(await screen.findByText(/cannot be made for a past day/)).toBeInTheDocument()
    expect(onCell).not.toHaveBeenCalled()
  })

  it('still opens the booking flow for today and later', async () => {
    const onCell = vi.fn()
    render(<ResourceCalendar mode="requester" onCellClick={onCell} />)
    fireEvent.click(await screen.findByLabelText(/Tue 03 Mar 2099/))
    expect(onCell).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/cannot be made for a past day/)).toBeNull()
  })

  it('lets an admin still open an existing booking on a past day', async () => {
    api.get.mockResolvedValue({ ...grid, resources: [{ ...grid.resources[0], days: [cell('2099-03-01', 'occupied', { past: true, bookings: [{ id: 'b1', status: 'approved', application_name: 'App' }] })] }] })
    const onCell = vi.fn()
    render(<ResourceCalendar mode="admin" onCellClick={onCell} />)
    fireEvent.click(await screen.findByLabelText(/Sun 01 Mar 2099/))
    expect(onCell).toHaveBeenCalledTimes(1)
  })
})
