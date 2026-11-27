import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Me', role: 'requester', products: [], product_name: null } }) }))

import { ReportEditor } from '../components/ReportEditor'
import { ReportLink } from '../components/ui'
import MyBookings from '../pages/requester/MyBookings'

const URL = 'https://contoso.sharepoint.com/sites/offsec/Reports/a.pdf'

describe('ReportLink', () => {
  it('is a new-tab link to the report when shared with a url', () => {
    render(<ReportLink shared type="Met" url={URL} />)
    const a = screen.getByRole('link', { name: /Met report/ })
    expect(a.getAttribute('href')).toBe(URL)
    expect(a.getAttribute('target')).toBe('_blank')
    expect(a.getAttribute('rel')).toContain('noopener')
  })
  it('falls back to the plain badge without a url or when not shared', () => {
    const { rerender } = render(<ReportLink shared type="V1" url={null} />)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Shared · V1 report')).toBeTruthy()
    rerender(<ReportLink shared={false} type={null} url={URL} />)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Not shared')).toBeTruthy()
  })
})

const b: any = { id: '11111111-aaaa-4bbb-8ccc-000000000001', application_name: 'Alpha App', application_version: '1', activity_name: 'Web PT', status: 'approved', requires_resource: true, report_shared: false, report_type: null, report_comments: null, report_url: null, report_shared_at: null }

describe('ReportEditor link field', () => {
  beforeEach(() => { api.put.mockReset(); api.put.mockResolvedValue(b) })
  it('needs a link when shared, and sends it trimmed', async () => {
    render(<ReportEditor booking={b} url="/x/report" onSaved={() => {}} />)
    fireEvent.click(screen.getByLabelText('Report shared'))
    fireEvent.change(screen.getByLabelText(/Report type/), { target: { value: 'V1' } })
    const save = screen.getByText('Save report details') as HTMLButtonElement
    expect(save.disabled).toBe(true)                      // no link yet
    fireEvent.change(screen.getByLabelText(/Report link/), { target: { value: `  ${URL} ` } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    expect(api.put).not.toHaveBeenCalled()                // the "Inform the POC?" question comes first
    fireEvent.click(await screen.findByText('No'))
    await waitFor(() => expect(api.put).toHaveBeenCalled())
    expect(api.put).toHaveBeenCalledWith('/x/report', { report_shared: true, report_type: 'V1', report_comments: null, report_url: URL, notify_poc: false })
  })
  it('Yes asks the server to email the POC; un-sharing saves without asking', async () => {
    const { unmount } = render(<ReportEditor booking={b} url="/x/report" onSaved={() => {}} />)
    fireEvent.click(screen.getByLabelText('Report shared'))
    fireEvent.change(screen.getByLabelText(/Report type/), { target: { value: 'V1' } })
    fireEvent.change(screen.getByLabelText(/Report link/), { target: { value: URL } })
    fireEvent.click(screen.getByText('Save report details'))
    expect(await screen.findByText('Inform the POC?')).toBeTruthy()
    fireEvent.click(screen.getByText('Yes, send email'))
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/x/report', expect.objectContaining({ notify_poc: true })))
    unmount()
    api.put.mockClear()
    const shared = { ...b, report_shared: true, report_type: 'V1', report_url: URL }
    render(<ReportEditor booking={shared} url="/x/report" onSaved={() => {}} />)
    fireEvent.click(screen.getByLabelText('Report shared'))      // un-share
    fireEvent.click(screen.getByText('Save report details'))
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/x/report', expect.objectContaining({ report_shared: false, notify_poc: false })))
    expect(screen.queryByText('Inform the POC?')).toBeNull()
  })
})

describe('Requester My Bookings', () => {
  it('shows the report link in the list and in the details', async () => {
    api.get.mockResolvedValue([{ ...b, report_shared: true, report_type: 'V1', report_url: URL, submitted_at: '2026-11-20T06:41:00Z', is_mine: true, requester_name: 'Me', start_date: '2027-09-01', end_date: '2027-09-10', resource_display_name: 'R', pci_dss_scope: false, pending_change_request: null }])
    render(<MemoryRouter><MyBookings /></MemoryRouter>)
    await screen.findByText('Alpha App')
    const links = screen.getAllByRole('link', { name: /V1 report/ })
    expect(links[0].getAttribute('href')).toBe(URL)
  })
})
