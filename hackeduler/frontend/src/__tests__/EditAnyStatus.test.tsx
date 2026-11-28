import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import { AdminBookingModal } from '../components/AdminBookingModal'

const base = {
  id: 'b1', status: 'completed', application_name: 'Portal', application_version: '1', pci_dss_scope: false, activity_type_id: 'a1', activity_name: 'Others',
  duration_days: 2, duration_overridden: false, additional_days: 0, requires_resource: true, resource_id: 'r1', resource_display_name: 'Resource 01', resource_code: 'R01',
  engineer_name: 'Eng One', extra_resources: [] as any[], start_date: '2027-03-01', end_date: '2027-03-02', poc_name: 'P', poc_email: 'p@x.com', requester_name: 'R', requester_email: 'r@x.com',
  product_id: null, implementation_id: null, additional_comments: null, report_shared: false,
}
const act = { id: 'a1', name: 'Others', is_active: true, base_duration_days: 2, requires_resource: true, deleted_at: null, allow_additional_days: false }

function setup(booking: any) {
  api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/bookings/') ? { booking, audit: [], conflicts: [], emails: [], status_history: [], locks: [] }
    : u.includes('activity-types') ? [act] : u.includes('/resources') ? [{ id: 'r1', code: 'R01', display_name: 'Resource 01', engineer_name: 'Eng 1', is_active: true }] : []))
  api.post.mockResolvedValue({})
  api.patch.mockResolvedValue({})
}
const open = async () => { render(<AdminBookingModal bookingId="b1" onClose={() => {}} />); fireEvent.click(await screen.findByRole('tab', { name: /Modify/ })) }

describe('Admin can modify a booking in any status', () => {
  beforeEach(() => { Object.values(api).forEach((m) => m.mockReset()) })

  it('completed: the whole form is available and saves', async () => {
    setup(base)
    await open()
    expect((await screen.findByLabelText('Start date') as HTMLInputElement).disabled).toBe(false)
    fireEvent.change(screen.getByLabelText('Version'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: 'fix' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][1]).toMatchObject({ application_version: '2', reason: 'fix' })
  })

  it('cancelled: details are editable, the schedule is locked with an explanation', async () => {
    setup({ ...base, status: 'cancelled' })
    await open()
    expect(await screen.findByText(/holds no reservation/)).toBeTruthy()
    expect(screen.getByLabelText('Start date').matches(':disabled')).toBe(true)
    expect(screen.getByLabelText('Version').matches(':disabled')).toBe(false)
  })
})
