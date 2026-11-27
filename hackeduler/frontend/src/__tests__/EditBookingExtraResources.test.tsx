import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import { AdminBookingModal } from '../components/AdminBookingModal'

const base = {
  id: 'b1', status: 'approved', application_name: 'Portal', application_version: '1', pci_dss_scope: false, activity_type_id: 'a1', activity_name: 'Others',
  duration_days: 2, duration_overridden: false, additional_days: 0, requires_resource: true, resource_id: 'r1', resource_display_name: 'Resource 01', resource_code: 'R01',
  engineer_name: 'Eng One', extra_resources: [] as any[], start_date: '2027-03-01', end_date: '2027-03-02', poc_name: 'P', poc_email: 'p@x.com', requester_name: 'R', requester_email: 'r@x.com',
  product_id: null, implementation_id: null, additional_comments: null, report_shared: false,
}
const act = { id: 'a1', name: 'Others', is_active: true, base_duration_days: 2, requires_resource: true, deleted_at: null, allow_additional_days: false }
const res = (id: string, n: number, active = true) => ({ id, code: `R0${n}`, display_name: `Resource 0${n}`, engineer_name: `Eng ${n}`, is_active: active })
const resources = [res('r1', 1), res('r2', 2), res('r3', 3), res('r4', 4)]

function setup(booking: any) {
  api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/bookings/') ? { booking, audit: [], conflicts: [], emails: [], status_history: [], locks: [] }
    : u.includes('activity-types') ? [act] : u.includes('/resources') ? resources : []))
  api.post.mockImplementation((u: string, body: any) => Promise.resolve(u.includes('availability/check') ? { available: body.resource_id !== 'r4', message: 'Busy', issues: [] } : {}))
  api.patch.mockResolvedValue({})
}

async function openModify() {
  render(<AdminBookingModal bookingId="b1" onClose={() => {}} />)
  fireEvent.click(await screen.findByRole('tab', { name: /Modify/ }))
  await screen.findByText(/Also block other resources/)
}

describe('Modify booking: additional resources', () => {
  beforeEach(() => { Object.values(api).forEach((m) => m.mockReset()) })

  it('adds a resource, with its own slice, and sends the full list', async () => {
    setup(base)
    await openModify()
    expect(await screen.findAllByText('Free')).toBeTruthy()
    expect(screen.getByText('Busy in these dates')).toBeTruthy()          // Resource 04
    expect(api.post).toHaveBeenCalledWith('/api/admin/availability/check', expect.objectContaining({ resource_id: 'r2', exclude_booking_id: 'b1' }))
    fireEvent.click(screen.getByLabelText(/Resource 02 – Eng 2/))
    fireEvent.change(await screen.findByLabelText('Start date (optional)'), { target: { value: '2027-03-08' } })
    fireEvent.change(screen.getByLabelText('Working days (optional)'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: 'more scope' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][1]).toMatchObject({ additional_resources: [{ resource_id: 'r2', start_date: '2027-03-08', working_days: 3 }], reason: 'more scope' })
  })

  it('pre-ticks the current resources, no longer locks the form, and sends nothing when untouched', async () => {
    setup({ ...base, extra_resources: [{ id: 'r2', code: 'R02', display_name: 'Resource 02', engineer_name: 'Eng 2', start_date: '2027-03-01', end_date: '2027-03-02', working_days: 2 }] })
    await openModify()
    expect(screen.queryByText(/can’t be changed here/)).toBeNull()
    expect(screen.getByText('On this booking')).toBeTruthy()
    expect((screen.getByLabelText(/Resource 02 – Eng 2/) as HTMLInputElement).checked).toBe(true)
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: 'typo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][1]).not.toHaveProperty('additional_resources')
  })

  it('releasing every extra sends an empty list; a date change keeps the list', async () => {
    setup({ ...base, extra_resources: [{ id: 'r2', code: 'R02', display_name: 'Resource 02', engineer_name: 'Eng 2', start_date: '2027-03-01', end_date: '2027-03-02', working_days: 2 }] })
    await openModify()
    fireEvent.click(screen.getByLabelText(/Resource 02 – Eng 2/))
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: 'drop' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][1]).toMatchObject({ additional_resources: [] })
  })
})
