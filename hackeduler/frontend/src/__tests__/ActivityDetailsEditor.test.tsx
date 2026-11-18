import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))

import ActivityTypes from '../pages/admin/ActivityTypes'
import { isEmptyRich, isRichHtml, toEditorHtml } from '../lib/emailDesign'

const act1 = { id: 'a1', name: 'Web Pentest', description: null, base_duration_days: 8, requires_resource: true, allow_additional_days: false, max_additional_days: 0,
  is_active: true, sort_order: 0, visible_to_requesters: true, initiation_email_enabled: true, initiation_days_before: null,
  initiation_details: '- Staging URL\n- VPN token', initiation_details_default: '- Application URL\n- Test accounts' }

describe('rich details helpers', () => {
  it('tells rich values from older text and detects empty editors', () => {
    expect(isRichHtml('<p>x</p>')).toBe(true); expect(isRichHtml('- a\n- b')).toBe(false)
    expect(toEditorHtml('- a\n- b')).toBe('<ul><li>a</li><li>b</li></ul>')
    expect(isEmptyRich('<p><br></p>')).toBe(true); expect(isEmptyRich('<p>&nbsp;</p>')).toBe(true)
    expect(isEmptyRich('<table><tr><td></td></tr></table>')).toBe(false); expect(isEmptyRich('<p>hi</p>')).toBe(false)
  })
})

describe('Activity type: details to ask the POC for', () => {
  beforeEach(() => {
    Object.values(api).forEach((m) => m.mockReset())
    api.get.mockResolvedValue([act1])
    api.post.mockResolvedValue({ html: '<html><body><table><tr><td>x</td></tr></table></body></html>', plain: 'x' })
    api.patch.mockResolvedValue({})
  })
  async function open() {
    render(<ActivityTypes />)
    fireEvent.click(await screen.findByRole('button', { name: /edit/i }))
    return await screen.findByTestId('rich-editor')
  }

  it('opens an older text value converted, inserts a table, previews it and saves HTML', async () => {
    const ed = await open()
    expect(ed.innerHTML).toBe('<ul><li>Staging URL</li><li>VPN token</li></ul>')
    fireEvent.change(screen.getByLabelText('Rows'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Columns'), { target: { value: '2' } })
    expect(screen.getByRole('button', { name: '+ Row' })).toBeDisabled()               // only inside a table cell
    ed.innerHTML = '<table><thead><tr><th>Role</th><th>Count</th></tr></thead><tbody><tr><td>Admin</td><td>1</td></tr></tbody></table>'
    fireEvent.input(ed)
    const box = await screen.findByTestId('details-preview')
    await waitFor(() => expect(box.querySelector('iframe')?.getAttribute('srcdoc')).toContain('<table'))
    expect(box.querySelector('iframe')!.getAttribute('sandbox')).toBe('')
    expect(api.post).toHaveBeenCalledWith('/api/admin/activity-types/details-preview', { details: expect.stringContaining('<table>') })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save' })) })
    expect(api.patch).toHaveBeenCalledWith('/api/admin/activity-types/a1', expect.objectContaining({ initiation_details: expect.stringContaining('<th>Role</th>') }))
  })

  it('saves an emptied editor as empty so the built-in checklist is used', async () => {
    const ed = await open()
    ed.innerHTML = '<p><br></p>'; fireEvent.input(ed)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save' })) })
    expect(api.patch).toHaveBeenCalledWith('/api/admin/activity-types/a1', expect.objectContaining({ initiation_details: null }))
  })

  it('can start from the built-in checklist', async () => {
    const ed = await open()
    fireEvent.click(screen.getByRole('button', { name: 'Start from the built-in checklist' }))
    await waitFor(() => expect(screen.getByTestId('rich-editor').innerHTML).toBe('<ul><li>Application URL</li><li>Test accounts</li></ul>'))
    expect(ed).toBeDefined()
  })
})
