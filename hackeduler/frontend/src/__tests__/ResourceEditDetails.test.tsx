import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), put: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
const toast = vi.hoisted(() => vi.fn())
vi.mock('../lib/toast', () => ({ useToast: () => toast }))

import Assignments from '../pages/resource/Assignments'

const row = (o: any = {}) => ({ id: 'b1', status: 'approved', application_name: 'Portal', application_version: '1.0', activity_name: 'Web PT', duration_days: 5,
  start_date: '2027-03-01', end_date: '2027-03-05', pci_dss_scope: true, poc_name: 'Priya', poc_email: 'priya@x.com', additional_comments: null, requester_name: 'Req',
  product_name: null, implementation_name: null, submitted_at: '2027-02-01T00:00:00Z', report_shared: false, report_type: null, report_comments: null, report_url: null, extra_resources: [], ...o })

async function open(r = row()) {
  api.get.mockResolvedValue({ total: 1, items: [r] })
  api.patch.mockResolvedValue({})
  render(<MemoryRouter><Assignments /></MemoryRouter>)
  fireEvent.click(await screen.findByText('Portal'))
}

describe('Resource: edit booking details', () => {
  beforeEach(() => { Object.values(api).forEach((m) => m.mockReset()); toast.mockReset() })

  it('needs a change and a reason, then sends only the changed fields', async () => {
    await open()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit details' }))
    const save = screen.getByRole('button', { name: 'Save changes' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('POC email(s)'), { target: { value: 'priya@x.com, ravi@x.com' } })
    expect(save.disabled).toBe(true)                                   // still no reason
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: 'Added Ravi' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch).toHaveBeenCalledWith('/api/resource/bookings/b1', { poc_email: 'priya@x.com, ravi@x.com', reason: 'Added Ravi' })
    expect(toast).toHaveBeenCalledWith('success', expect.stringMatching(/requester have been emailed/))
  })

  it('rejects an invalid POC email and has no date, activity, resource or product fields', async () => {
    await open()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit details' }))
    fireEvent.change(screen.getByLabelText('POC email(s)'), { target: { value: 'nope' } })
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: 'x' } })
    expect((screen.getByRole('button', { name: 'Save changes' }) as HTMLButtonElement).disabled).toBe(true)
    const form = within(screen.getByRole('form', { name: 'Edit booking details' }))
    for (const l of [/Start date/, /End date/, /Activity/, /^Resource/, /Product/, /Implementation/]) expect(form.queryByLabelText(l)).toBeNull()
  })

  it('is only offered on approved bookings', async () => {
    await open(row({ status: 'completed' }))
    await screen.findByText('PCI DSS scope')
    expect(screen.queryByRole('button', { name: 'Edit details' })).toBeNull()
  })
})
