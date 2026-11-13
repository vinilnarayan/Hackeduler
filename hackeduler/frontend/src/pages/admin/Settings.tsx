import { useEffect, useState } from 'react'
import { get, post, put, validationMessage } from '../../api/client'
import { ErrorState, Field, PageHeader, Spinner } from '../../components/ui'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function SettingsPage() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<any>(() => get('/api/admin/settings'))
  const [v, setV] = useState<any>(null)
  const [testTo, setTestTo] = useState('')
  const [testing, setTesting] = useState('')
  useEffect(() => { if (data) setV({ ...data.values, admin_notification_recipients: (data.values.admin_notification_recipients ?? []).join(', ') }) }, [data])
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !v) return <Spinner />
  const save = async () => {
    const values = { ...v, admin_notification_recipients: v.admin_notification_recipients.split(',').map((s: string) => s.trim()).filter(Boolean),
      pending_expiry_hours: Number(v.pending_expiry_hours), initiation_email_days_before: Number(v.initiation_email_days_before), smtp_port: v.smtp_port === '' || v.smtp_port === null ? null : Number(v.smtp_port),
      smtp_host: v.smtp_host || null, smtp_username: v.smtp_username || null,
      email_primary: v.email_primary || null, email_fallback: v.email_fallback || null,
      ses_region: v.ses_region || null, ses_configuration_set: v.ses_configuration_set || null }
    try { await put('/api/admin/settings', { values }); toast('success', 'Settings saved'); reload() } catch (e) { toast('error', validationMessage(e)) }
  }
  const env = data.environment
  const sendTest = async (provider: 'smtp' | 'ses' | null) => {
    setTesting(provider ?? 'chain')
    try {
      const r = await post<{ ok: boolean; provider: string | null; error: string | null }>('/api/admin/settings/test-email', { to: testTo, ...(provider ? { provider } : {}) })
      if (r.ok) toast('success', `Test email sent through ${String(r.provider).toUpperCase()} to ${testTo}`)
      else toast('error', `Test email failed: ${r.error}`)
    } catch (e) { toast('error', validationMessage(e)) } finally { setTesting('') }
  }
  const chain: string[] = data.email_chain ?? ['smtp']
  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader title="Settings" actions={<button className="btn-primary" onClick={save}>Save settings</button>} />
      <section className="card space-y-3 p-4">
        <h2 className="text-sm font-semibold">Scheduling</h2>
        <Field label="Organisation timezone" htmlFor="s-tz" hint="IANA name, e.g. Asia/Kolkata"><input id="s-tz" className="input" value={v.timezone} onChange={(e) => setV({ ...v, timezone: e.target.value })} /></Field>
        <fieldset><legend className="label">Working weekdays</legend><div className="flex flex-wrap gap-3 text-sm">{DAYS.map((d, i) => (
          <label key={d} className="flex items-center gap-1"><input type="checkbox" checked={v.working_weekdays.includes(i)} onChange={(e) => setV({ ...v, working_weekdays: e.target.checked ? [...v.working_weekdays, i].sort() : v.working_weekdays.filter((x: number) => x !== i) })} />{d}</label>
        ))}</div></fieldset>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.pending_expiry_enabled} onChange={(e) => setV({ ...v, pending_expiry_enabled: e.target.checked })} />Expire pending requests automatically (releases the reservation)</label>
        <Field label="Pending reservation expiry (hours)" htmlFor="s-ph"><input id="s-ph" type="number" min={1} className="input w-40" value={v.pending_expiry_hours} onChange={(e) => setV({ ...v, pending_expiry_hours: e.target.value })} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.requester_direct_cancel_pending} onChange={(e) => setV({ ...v, requester_direct_cancel_pending: e.target.checked })} />Requesters may cancel their own pending requests without admin approval (approved bookings always require a request)</label>
      </section>
      <section className="card space-y-3 p-4">
        <h2 className="text-sm font-semibold">Activity initiation email</h2>
        <p className="text-xs text-slate-500">Asks the POC for the details needed before testing (URLs, test accounts, scope, IP whitelisting…). Sent once for each approved booking that has a start date, and again if it is rescheduled. Edit the wording under Email &amp; Templates; set a different number of days (or turn it off) for one activity type under Activity Types.</p>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!v.initiation_email_enabled} onChange={(e) => setV({ ...v, initiation_email_enabled: e.target.checked })} />Send the Activity initiation email automatically</label>
        <Field label="Days before the start date" htmlFor="s-id" hint="Default 7. Use 0 to send on the start date itself."><input id="s-id" type="number" min={0} max={365} className="input w-40" disabled={!v.initiation_email_enabled} value={v.initiation_email_days_before} onChange={(e) => setV({ ...v, initiation_email_days_before: e.target.value })} /></Field>
      </section>
      <section className="card space-y-3 p-4">
        <h2 className="text-sm font-semibold">Email notifications</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Sender name" htmlFor="s-sn"><input id="s-sn" className="input" value={v.email_sender_name} onChange={(e) => setV({ ...v, email_sender_name: e.target.value })} /></Field>
          <Field label="Sender address" htmlFor="s-sa"><input id="s-sa" type="email" className="input" value={v.email_sender_address} onChange={(e) => setV({ ...v, email_sender_address: e.target.value })} /></Field>
        </div>
        <Field label="Admin notification recipients" htmlFor="s-ar" hint="Comma-separated. Receive new-request and change-request emails."><input id="s-ar" className="input" value={v.admin_notification_recipients} onChange={(e) => setV({ ...v, admin_notification_recipients: e.target.value })} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.notify_requester_copy} onChange={(e) => setV({ ...v, notify_requester_copy: e.target.checked })} />Copy the requester on POC notifications</label>
        <h3 className="pt-2 text-sm font-semibold">Mail service</h3>
        <p className="text-xs text-slate-500">Choose how email leaves the system. Use Amazon SES (sent through the AWS API, using the server&apos;s IAM role - no password to store) and/or an SMTP server. If a fallback is set, an email that cannot be sent by the first service is tried on the second before it counts as a failed attempt.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Primary service" htmlFor="s-ep" hint={`Server default: ${env.email_primary}`}>
            <select id="s-ep" className="input" value={v.email_primary ?? ''} onChange={(e) => setV({ ...v, email_primary: e.target.value })}>
              <option value="">Server default ({env.email_primary})</option><option value="smtp">SMTP server</option><option value="ses">Amazon SES</option>
            </select>
          </Field>
          <Field label="Fallback service" htmlFor="s-ef" hint={`Server default: ${env.email_fallback}`}>
            <select id="s-ef" className="input" value={v.email_fallback ?? ''} onChange={(e) => setV({ ...v, email_fallback: e.target.value })}>
              <option value="">Server default ({env.email_fallback})</option><option value="none">No fallback</option><option value="smtp">SMTP server</option><option value="ses">Amazon SES</option>
            </select>
          </Field>
        </div>
        <p className="text-xs text-slate-600">Mail is currently sent through: <b>{chain.map((c) => (c === 'ses' ? 'Amazon SES' : 'SMTP')).join(' → ')}</b>{chain.length > 1 ? ' (second one only if the first fails)' : ''}.</p>
        <div className="space-y-3 rounded-lg border border-slate-200 p-3">
          <div className="text-sm font-medium">Amazon SES</div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="AWS region" htmlFor="s-sr" hint={`e.g. ap-south-1. Server default: ${env.aws_region ?? 'AWS_REGION of the server'}`}><input id="s-sr" className="input" value={v.ses_region ?? ''} onChange={(e) => setV({ ...v, ses_region: e.target.value })} /></Field>
            <Field label="Configuration set (optional)" htmlFor="s-sc" hint={env.ses_configuration_set ? `Server default: ${env.ses_configuration_set}` : 'For bounce / delivery tracking'}><input id="s-sc" className="input" value={v.ses_configuration_set ?? ''} onChange={(e) => setV({ ...v, ses_configuration_set: e.target.value })} /></Field>
          </div>
          <p className="text-xs text-slate-500">The sender address above must be a verified identity in SES. Credentials come from the EC2 instance role; nothing secret is entered or stored here.</p>
        </div>
        <div className="space-y-3 rounded-lg border border-slate-200 p-3">
          <div className="text-sm font-medium">SMTP server</div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="SMTP host override" htmlFor="s-h" hint={`Env: ${env.smtp_host}`}><input id="s-h" className="input" value={v.smtp_host ?? ''} onChange={(e) => setV({ ...v, smtp_host: e.target.value })} /></Field>
            <Field label="SMTP port override" htmlFor="s-p" hint={`Env: ${env.smtp_port}`}><input id="s-p" type="number" className="input" value={v.smtp_port ?? ''} onChange={(e) => setV({ ...v, smtp_port: e.target.value })} /></Field>
            <Field label="SMTP username override" htmlFor="s-u"><input id="s-u" className="input" value={v.smtp_username ?? ''} onChange={(e) => setV({ ...v, smtp_username: e.target.value })} /></Field>
          </div>
          <p className="rounded bg-slate-50 p-2 text-xs text-slate-600">Email backend: <b>{env.email_backend}</b> · SMTP password configured: <b>{env.smtp_password_configured ? 'yes' : 'no'}</b>. The password is read from the <code>HACKEDULER_SMTP_PASSWORD</code> environment variable only and is never shown or stored here.</p>
        </div>
        <div className="space-y-2 rounded-lg border border-slate-200 p-3">
          <div className="text-sm font-medium">Send a test email</div>
          <p className="text-xs text-slate-500">Uses the settings as last saved - click &quot;Save settings&quot; first after changing anything above.</p>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Send to" htmlFor="s-tt"><input id="s-tt" type="email" className="input w-64" placeholder="you@example.com" value={testTo} onChange={(e) => setTestTo(e.target.value)} /></Field>
            <button className="btn-secondary" disabled={!testTo || !!testing} onClick={() => sendTest(null)}>{testing === 'chain' ? 'Sending…' : 'Test current setup'}</button>
            <button className="btn-secondary" disabled={!testTo || !!testing} onClick={() => sendTest('ses')}>{testing === 'ses' ? 'Sending…' : 'Test SES only'}</button>
            <button className="btn-secondary" disabled={!testTo || !!testing} onClick={() => sendTest('smtp')}>{testing === 'smtp' ? 'Sending…' : 'Test SMTP only'}</button>
          </div>
        </div>
      </section>
    </div>
  )
}
