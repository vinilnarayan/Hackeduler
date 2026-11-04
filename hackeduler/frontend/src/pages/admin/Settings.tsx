import { useEffect, useState } from 'react'
import { get, put, validationMessage } from '../../api/client'
import { ErrorState, Field, PageHeader, Spinner } from '../../components/ui'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function SettingsPage() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<any>(() => get('/api/admin/settings'))
  const [v, setV] = useState<any>(null)
  useEffect(() => { if (data) setV({ ...data.values, admin_notification_recipients: (data.values.admin_notification_recipients ?? []).join(', ') }) }, [data])
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !v) return <Spinner />
  const save = async () => {
    const values = { ...v, admin_notification_recipients: v.admin_notification_recipients.split(',').map((s: string) => s.trim()).filter(Boolean),
      pending_expiry_hours: Number(v.pending_expiry_hours), smtp_port: v.smtp_port === '' || v.smtp_port === null ? null : Number(v.smtp_port),
      smtp_host: v.smtp_host || null, smtp_username: v.smtp_username || null }
    try { await put('/api/admin/settings', { values }); toast('success', 'Settings saved'); reload() } catch (e) { toast('error', validationMessage(e)) }
  }
  const env = data.environment
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
        <h2 className="text-sm font-semibold">Email notifications</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Sender name" htmlFor="s-sn"><input id="s-sn" className="input" value={v.email_sender_name} onChange={(e) => setV({ ...v, email_sender_name: e.target.value })} /></Field>
          <Field label="Sender address" htmlFor="s-sa"><input id="s-sa" type="email" className="input" value={v.email_sender_address} onChange={(e) => setV({ ...v, email_sender_address: e.target.value })} /></Field>
        </div>
        <Field label="Admin notification recipients" htmlFor="s-ar" hint="Comma-separated. Receive new-request and change-request emails."><input id="s-ar" className="input" value={v.admin_notification_recipients} onChange={(e) => setV({ ...v, admin_notification_recipients: e.target.value })} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.notify_requester_copy} onChange={(e) => setV({ ...v, notify_requester_copy: e.target.checked })} />Copy the requester on POC notifications</label>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="SMTP host override" htmlFor="s-h" hint={`Env: ${env.smtp_host}`}><input id="s-h" className="input" value={v.smtp_host ?? ''} onChange={(e) => setV({ ...v, smtp_host: e.target.value })} /></Field>
          <Field label="SMTP port override" htmlFor="s-p" hint={`Env: ${env.smtp_port}`}><input id="s-p" type="number" className="input" value={v.smtp_port ?? ''} onChange={(e) => setV({ ...v, smtp_port: e.target.value })} /></Field>
          <Field label="SMTP username override" htmlFor="s-u"><input id="s-u" className="input" value={v.smtp_username ?? ''} onChange={(e) => setV({ ...v, smtp_username: e.target.value })} /></Field>
        </div>
        <p className="rounded bg-slate-50 p-2 text-xs text-slate-600">Email backend: <b>{env.email_backend}</b> · SMTP password configured: <b>{env.smtp_password_configured ? 'yes' : 'no'}</b>. The password is read from the <code>HACKEDULER_SMTP_PASSWORD</code> environment variable only and is never shown or stored here.</p>
      </section>
    </div>
  )
}
