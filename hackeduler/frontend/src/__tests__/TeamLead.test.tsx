import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() }))
const auth = vi.hoisted(() => ({ user: { id: 'u1', full_name: 'Asha', email: 'a@x.com', role: 'resource', is_lead: true } as any }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: auth.user, logout: vi.fn() }) }))

import { Layout } from '../components/Layout'
import TeamCalendar from '../pages/admin/TeamCalendar'
import UsersPage from '../pages/admin/Users'

describe('Team lead', () => {
  beforeEach(() => { Object.values(api).forEach((f) => f.mockReset()); auth.user = { id: 'u1', full_name: 'Asha', email: 'a@x.com', role: 'resource', is_lead: true } })

  it('adds a Team Calendar to the menu for a lead, but not for another resource user', () => {
    const { unmount } = render(<MemoryRouter><Layout /></MemoryRouter>)
    expect(screen.getAllByRole('link', { name: /Team Calendar/ }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: /Team Calendar/ })[0]).toHaveAttribute('href', '/team-calendar')
    unmount()
    auth.user = { ...auth.user, is_lead: false }
    render(<MemoryRouter><Layout /></MemoryRouter>)
    expect(screen.queryByRole('link', { name: /Team Calendar/ })).toBeNull()
    expect(screen.getAllByRole('link', { name: /My Assignments/ }).length).toBeGreaterThan(0)
  })

  it('the lead calendar uses the lead endpoint and has no links into the admin pages', async () => {
    const entry = { booking_id: 'b1', resource_id: 'r1', resource_name: 'Resource 01', engineer_name: 'Eng 1', application_name: 'App1', application_version: '1', activity_name: 'Web PT', status: 'approved', tentative: false, start_date: '2099-03-02', end_date: '2099-03-03' }
    api.get.mockResolvedValue({ month: '2099-03', week: null, today: '2099-03-02', resources: [{ id: 'r1', display_name: 'Resource 01', engineer_name: 'Eng 1', is_active: true }],
      summary: { working_days: 5, booked_days: 1, leave_days: 0, holidays: 0 },
      days: [{ date: '2099-03-02', in_month: true, weekend: false, holiday: null, entries: [entry], leaves: [], free: [] }] })
    render(<MemoryRouter><TeamCalendar mode="lead" /></MemoryRouter>)
    fireEvent.click(await screen.findByLabelText(/2099-03-02: 1 activities/))
    expect((await screen.findAllByText('App1 v1')).length).toBeGreaterThan(0)
    await screen.findByRole('heading', { name: 'Activities' })
    expect(screen.queryByRole('link', { name: /App1/ })).toBeNull()
    expect(api.get.mock.calls.every((c) => String(c[0]).startsWith('/api/resource/team-calendar'))).toBe(true)
  })

  it('admin can mark a resource user as a lead when creating or editing', async () => {
    auth.user = { id: 'admin1', full_name: 'Admin', email: 'ad@x.com', role: 'admin' }
    const lead = { id: '2', full_name: 'Lena Lead', email: 'lena@x.com', role: 'resource', is_active: true, has_password: true, is_lead: true, resource_id: 'r1', resource_name: 'Resource 01', products: [], extra_product_ids: [] }
    api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/users') ? [lead] : u.startsWith('/api/admin/resources') ? [{ id: 'r1', display_name: 'Resource 01', engineer_name: 'Lena' }] : []))
    api.patch.mockResolvedValue({})
    render(<MemoryRouter><UsersPage /></MemoryRouter>)
    await screen.findByText('Lena Lead')
    expect(screen.getByText('Lead', { selector: 'td span' })).toBeTruthy()                  // pill in the table
    expect(screen.getByTestId('user-counts').textContent).toMatch(/Leads 1/)
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const box = (await screen.findByLabelText(/Team lead/)) as HTMLInputElement
    expect(box.checked).toBe(true)
    fireEvent.click(box)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][1].is_lead).toBe(false)
    // searchable
    fireEvent.change(screen.getByLabelText('Search users'), { target: { value: 'lead' } })
    expect(screen.getByText('Lena Lead')).toBeTruthy()
  })
})
