import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import { AdminBookingModal } from '../components/AdminBookingModal'

const booking = {
  id: 'b1', status: 'approved', application_name: 'Portal', application_version: '1', pci_dss_scope: false, activity_type_id: 'a1', activity_name: 'Others',
  duration_days: 2, duration_overridden: false, additional_days: 0, requires_resource: true, resource_id: 'r1', resource_display_name: 'Resource 01', resource_code: 'R01',
  engineer_name: 'Eng', extra_resources: [], start_date: '2027-03-01', end_date: '2027-03-02', poc_name: 'P', poc_email: 'p@x.com', requester_name: 'R', requester_email: 'r@x.com',
  product_id: null, implementation_id: null, additional_comments: null, report_shared: false,
}
const act = { id: 'a1', name: 'Others', is_active: true, base_duration_days: 2, requires_resource: true, deleted_at: null, allow_additional_days: false }
const range = {
  start_date: '2027-03-01', end_date: '2027-03-10', calendar_days: 10, working_days: 7, work_dates: [], skipped: { weekend: 2, holiday: 1, leave: 0 },
  skipped_dates: [{ date: '2027-03-09', reason: 'holiday', label: 'Spring Fest' }], leave_considered: true, available: true, issues: [], message: '',
}

describe('Modify booking: end date', () => {
  beforeEach(() => {
    Object.values(api).forEach((m) => m.mockReset())
    api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/bookings/') ? { booking, audit: [], conflicts: [], emails: [], status_history: [], locks: [] } : u.includes('activity-types') ? [act] : []))
    api.post.mockResolvedValue(range)
    api.patch.mockResolvedValue({})
  })

  it('always shows the end date, and editing it previews and sends the new end date', async () => {
    render(<AdminBookingModal bookingId="b1" onClose={() => {}} />)
    fireEvent.click(await screen.findByRole('tab', { name: /Modify/ }))
    const end = (await screen.findByLabelText('End date')) as HTMLInputElement
    expect(end.value).toBe('2027-03-02')
    fireEvent.change(end, { target: { value: '2027-03-10' } })
    expect((await screen.findByTestId('edit-range')).textContent).toMatch(/7 working days of 10 calendar days/)
    expect(api.post).toHaveBeenCalledWith('/api/admin/availability/range', expect.objectContaining({ end_date: '2027-03-10', exclude_booking_id: 'b1', resource_id: 'r1' }))
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: 'extend' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][1]).toMatchObject({ end_date: '2027-03-10', reason: 'extend' })
  })

  it('sends no end date when it is left unchanged', async () => {
    render(<AdminBookingModal bookingId="b1" onClose={() => {}} />)
    fireEvent.click(await screen.findByRole('tab', { name: /Modify/ }))
    await screen.findByLabelText('End date')
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][1]).not.toHaveProperty('end_date')
  })
})
