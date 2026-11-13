import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))

import SettingsPage from '../pages/admin/Settings'

const settings = {
  values: {
    timezone: 'Asia/Kolkata', working_weekdays: [0, 1, 2, 3, 4], pending_expiry_enabled: true, pending_expiry_hours: 72,
    requester_direct_cancel_pending: true, email_sender_name: 'Hackeduler', email_sender_address: 'noreply@example.com',
    admin_notification_recipients: ['a@example.com'], notify_requester_copy: true, initiation_email_enabled: true,
    initiation_email_days_before: 7, smtp_host: null, smtp_port: null, smtp_username: null, smtp_starttls: null,
    email_primary: null, email_fallback: null, ses_region: null, ses_configuration_set: null,
  },
  environment: { email_backend: 'smtp', smtp_host: 'smtp.corp', smtp_port: 25, smtp_password_configured: false, email_primary: 'smtp', email_fallback: 'none', aws_region: null, ses_configuration_set: null },
  email_chain: ['smtp'],
}

describe('Settings: mail service', () => {
  beforeEach(() => { api.get.mockResolvedValue(settings); api.put.mockResolvedValue({}); api.post.mockResolvedValue({ ok: true, provider: 'ses', error: null }) })

  it('saves the chosen primary, fallback and SES region', async () => {
    render(<SettingsPage />)
    fireEvent.change(await screen.findByLabelText('Primary service'), { target: { value: 'ses' } })
    fireEvent.change(screen.getByLabelText('Fallback service'), { target: { value: 'smtp' } })
    fireEvent.change(screen.getByLabelText(/AWS region/), { target: { value: 'ap-south-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() => expect(api.put).toHaveBeenCalled())
    const sent = api.put.mock.calls[0][1].values
    expect(sent).toMatchObject({ email_primary: 'ses', email_fallback: 'smtp', ses_region: 'ap-south-1', ses_configuration_set: null })
  })

  it('leaves everything on the server defaults when untouched', async () => {
    render(<SettingsPage />)
    await screen.findByLabelText('Primary service')
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() => expect(api.put).toHaveBeenCalled())
    expect(api.put.mock.calls[0][1].values).toMatchObject({ email_primary: null, email_fallback: null, ses_region: null })
  })

  it('sends a test email through SES only', async () => {
    render(<SettingsPage />)
    const to = await screen.findByLabelText('Send to')
    expect(screen.getByRole('button', { name: 'Test SES only' })).toBeDisabled()
    fireEvent.change(to, { target: { value: 'me@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test SES only' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/admin/settings/test-email', { to: 'me@example.com', provider: 'ses' }))
  })
})
