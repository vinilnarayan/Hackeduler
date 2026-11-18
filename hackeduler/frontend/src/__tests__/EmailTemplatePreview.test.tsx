import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))

import EmailPage from '../pages/admin/Email'
import { textToHtml } from '../lib/emailDesign'

const tpl = { key: 'booking_approved_poc', name: 'Booking approved (to POC)', subject_template: 'Approved: {{Application Name}}', body_template: '# Hi\n**Bold** text\n\n- one\n- two',
  body_format: 'text', layout: 'classic', accent: '#0f2744', is_active: true }

describe('textToHtml', () => {
  it('converts the older text syntax and escapes markup', () => {
    expect(textToHtml('# Hi\n**B** [x](https://a.example)\n\n- one\n- two\n<script>')).toBe(
      '<h2>Hi</h2><p><strong>B</strong> <a href="https://a.example">x</a></p><ul><li>one</li><li>two</li></ul><p>&lt;script&gt;</p>')
  })
  it('ignores unsafe links', () => { expect(textToHtml('[x](javascript:alert(1))')).not.toContain('<a ') })
})

describe('Email template visual editor', () => {
  beforeEach(() => {
    Object.values(api).forEach((m) => m.mockReset())
    api.get.mockImplementation((u: string) => Promise.resolve(u.endsWith('/variables') ? ['Application Name', 'Requester Name'] : [tpl]))
    api.post.mockResolvedValue({ subject: 'Approved: <Application Name>', body: 'Hi\nBold text', html: '<html><body><strong>Bold</strong> text</body></html>' })
    api.put.mockResolvedValue({})
  })

  async function openEditor() {
    render(<EmailPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await screen.findByTestId('rich-editor')
  }

  it('opens an older template converted to the visual editor, with a live sandboxed preview', async () => {
    await openEditor()
    expect(screen.getByTestId('rich-editor').innerHTML).toContain('<h2>Hi</h2>')
    expect(screen.getByText(/older text style/)).toBeInTheDocument()
    const box = await screen.findByTestId('email-preview')
    await waitFor(() => expect(box.querySelector('iframe')).not.toBeNull())
    const frame = box.querySelector('iframe')!
    expect(frame.getAttribute('sandbox')).toBe('')
    expect(frame.getAttribute('srcdoc')).toContain('<strong>Bold</strong>')
    expect(box.textContent).toContain('Subject: Approved: <Application Name>')
    expect(box.textContent).toContain('Plain-text version')
    expect(api.post.mock.calls[0][1]).toMatchObject({ body_format: 'html', layout: 'classic', accent: '#0f2744' })
  })

  it('changes design, colour and device, and re-renders the preview', async () => {
    await openEditor()
    fireEvent.click(screen.getByRole('button', { name: 'Banner' }))
    fireEvent.click(screen.getByRole('button', { name: 'Teal' }))
    await waitFor(() => expect(api.post).toHaveBeenLastCalledWith(expect.stringContaining('/preview'), expect.objectContaining({ layout: 'banner', accent: '#0f766e' })))
    fireEvent.click(screen.getByRole('button', { name: 'Phone' }))
    const frame = (await screen.findByTestId('email-preview')).querySelector('iframe')!
    expect(frame.style.width).toBe('360px')
    expect(screen.getByLabelText('Custom colour')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Navy|Blue|Cyan|Teal|Green|Olive|Amber|Rust|Red|Pink|Purple|Indigo|Slate|Black/ }).length).toBeGreaterThanOrEqual(12)
  })

  it('inserts a variable and saves the design', async () => {
    await openEditor()
    fireEvent.click(screen.getByRole('button', { name: 'Banner' }))
    const ed = screen.getByTestId('rich-editor')
    ed.innerHTML = '<p>Hello</p>'
    fireEvent.input(ed)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save' })) })
    expect(api.put).toHaveBeenCalledWith('/api/admin/email-templates/booking_approved_poc',
      expect.objectContaining({ body_template: '<p>Hello</p>', body_format: 'html', layout: 'banner', accent: '#0f2744' }))
  })

  it('has table tools in the body editor, enabled only inside a table, and saves the table', async () => {
    await openEditor()
    expect(screen.getByLabelText('Rows')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Insert table' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Column' })).toBeDisabled()
    const ed = screen.getByTestId('rich-editor')
    ed.innerHTML = '<table><thead><tr><th>Engineer</th><th>From</th></tr></thead><tbody><tr><td>{{Requester Name}}</td><td>{{Application Name}}</td></tr></tbody></table>'
    fireEvent.input(ed)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save' })) })
    expect(api.put).toHaveBeenCalledWith('/api/admin/email-templates/booking_approved_poc',
      expect.objectContaining({ body_format: 'html', body_template: expect.stringContaining('<th>Engineer</th>') }))
  })

  it('rejects a link that is not http(s)', async () => {
    await openEditor()
    fireEvent.change(screen.getByLabelText('Link address'), { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(screen.getByRole('button', { name: 'Make link' }))
    expect(screen.getByText(/starting with http/)).toBeInTheDocument()
  })
})
