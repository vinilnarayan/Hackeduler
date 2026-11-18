import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))

import EmailPage from '../pages/admin/Email'

const tpl = { key: 'booking_approved_poc', name: 'Booking approved (to POC)', subject_template: 'Approved: {{Application Name}}', body_template: '# Hi\n**Bold** text', is_active: true }

describe('Email template editor', () => {
  beforeEach(() => {
    Object.values(api).forEach((m) => m.mockReset())
    api.get.mockImplementation((u: string) => Promise.resolve(u.endsWith('/variables') ? ['Application Name'] : [tpl]))
    api.post.mockResolvedValue({ subject: 'Approved: <Application Name>', body: 'Hi\nBold text', html: '<html><body><strong>Bold</strong> text</body></html>' })
  })

  it('previews the formatted HTML email in a sandboxed frame, with the plain-text version available', async () => {
    render(<EmailPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    expect(await screen.findByText(/Formatting: \*\*bold\*\*/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    const box = await screen.findByTestId('email-preview')
    const frame = box.querySelector('iframe')!
    expect(frame.getAttribute('sandbox')).toBe('')                       // no scripts, no navigation
    expect(frame.getAttribute('srcdoc')).toContain('<strong>Bold</strong>')
    expect(box.textContent).toContain('Subject: Approved: <Application Name>')
    expect(box.textContent).toContain('Plain-text version')
  })
})
