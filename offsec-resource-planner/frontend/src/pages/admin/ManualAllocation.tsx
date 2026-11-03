import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, CheckCircle2 } from 'lucide-react'
import { get, post, validationMessage } from '../../api/client'
import type { ActivityType, AdminBooking, AvailabilityResult, ForcePayload, ResourceAdmin } from '../../api/types'
import { useForceFlow } from '../../components/useForceFlow'
import { Field, PageHeader } from '../../components/ui'
import { fmt } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function ManualAllocation() {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const toast = useToast()
  const force = useForceFlow()
  const resources = useAsync<ResourceAdmin[]>(() => get('/api/admin/resources'))
  const acts = useAsync<ActivityType[]>(() => get('/api/admin/activity-types'))
  const [f, setF] = useState({
    resource_id: sp.get('resource') ?? '', activity_type_id: '', start_date: sp.get('start') ?? '', additional_days: 0,
    duration_mode: 'activity' as 'activity' | 'duration' | 'end_date', duration_days: 1, end_date: '', initial_status: 'approved',
    application_name: '', application_version: '', pci: 'no', poc_name: '', poc_email: '', additional_comments: '', reason: '',
  })
  const [check, setCheck] = useState<AvailabilityResult | null>(null)
  const [busy, setBusy] = useState(false)
  const s = (k: keyof typeof f) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.type === 'number' ? parseInt(e.target.value || '0', 10) : e.target.value })

  useEffect(() => {
    setCheck(null)
    if (!f.resource_id || !f.activity_type_id || !f.start_date) return
    const t = setTimeout(() => post<AvailabilityResult>('/api/admin/availability/check', { resource_id: f.resource_id, activity_type_id: f.activity_type_id, start_date: f.start_date, additional_days: f.additional_days }).then(setCheck).catch((e) => toast('error', validationMessage(e))), 250)
    return () => clearTimeout(t)
  }, [f.resource_id, f.activity_type_id, f.start_date, f.additional_days])

  const body = (fp?: ForcePayload) => ({
    resource_id: f.resource_id, activity_type_id: f.activity_type_id, start_date: f.start_date, additional_days: f.additional_days,
    duration_days: f.duration_mode === 'duration' ? f.duration_days : null, end_date: f.duration_mode === 'end_date' ? f.end_date : null,
    initial_status: f.initial_status, application_name: f.application_name, application_version: f.application_version,
    pci_dss_scope: f.pci === 'yes', poc_name: f.poc_name, poc_email: f.poc_email, additional_comments: f.additional_comments || null,
    reason: f.reason || null, ...(fp ? { force: fp } : {}),
  })
  const act = acts.data?.find((a) => a.id === f.activity_type_id)
  const valid = f.resource_id && f.activity_type_id && f.start_date && f.application_name && f.application_version && f.poc_name && f.poc_email
  return (
    <div className="max-w-5xl">
      <PageHeader title="Manual Allocation" subtitle="Create a booking directly, bypassing the requester workflow. If a conflict or restriction is detected you will be asked to confirm a Force Allocate." />
      <form className="card space-y-4 p-4" onSubmit={async (e) => {
        e.preventDefault(); setBusy(true)
        await force.run((fp) => post<AdminBooking>('/api/admin/bookings', body(fp)), (b) => { toast('success', `Booking ${b.id} created`); nav('/admin/bookings?q=' + b.id) })
        setBusy(false)
      }}>
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Resource *" htmlFor="m-res"><select id="m-res" className="input" value={f.resource_id} onChange={s('resource_id')}><option value="">Select…</option>{resources.data?.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}{r.is_active ? '' : ' (inactive)'}</option>)}</select></Field>
          <Field label="Activity type *" htmlFor="m-act"><select id="m-act" className="input" value={f.activity_type_id} onChange={s('activity_type_id')}><option value="">Select…</option>{acts.data?.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.name} ({a.base_duration_days}d){a.description ? ` – ${a.description}` : ''}</option>)}</select></Field>
          <Field label="Start date *" htmlFor="m-sd"><input id="m-sd" type="date" className="input" value={f.start_date} onChange={s('start_date')} /></Field>
          <Field label="Duration" htmlFor="m-dm"><select id="m-dm" className="input" value={f.duration_mode} onChange={s('duration_mode')}><option value="activity">From activity type</option><option value="duration">Override working days</option><option value="end_date">Explicit end date</option></select></Field>
          {f.duration_mode === 'duration' && <Field label="Working days" htmlFor="m-dd"><input id="m-dd" type="number" min={1} max={250} className="input" value={f.duration_days} onChange={s('duration_days')} /></Field>}
          {f.duration_mode === 'end_date' && <Field label="End date" htmlFor="m-ed"><input id="m-ed" type="date" className="input" value={f.end_date} onChange={s('end_date')} /></Field>}
          {act?.allow_additional_days && f.duration_mode === 'activity' && <Field label="Additional days" htmlFor="m-ad"><input id="m-ad" type="number" min={0} max={act.max_additional_days} className="input" value={f.additional_days} onChange={s('additional_days')} /></Field>}
          <Field label="Initial status" htmlFor="m-st"><select id="m-st" className="input" value={f.initial_status} onChange={s('initial_status')}><option value="approved">Approved (POC notified)</option><option value="pending_approval">Pending approval</option></select></Field>
        </div>
        {check && (
          <div className={`rounded-md border p-3 text-sm ${check.available ? 'border-emerald-300 bg-emerald-50' : 'border-amber-300 bg-amber-50'}`} aria-live="polite">
            <div className="flex items-center gap-2 font-semibold">{check.available ? <CheckCircle2 className="h-4 w-4 text-emerald-700" /> : <AlertCircle className="h-4 w-4 text-amber-700" />}{check.available ? 'Available' : check.message}</div>
            <div className="mt-1 text-xs">Standard calculation: {fmt(check.start_date)} – {fmt(check.end_date)} ({check.duration_days} working days){f.duration_mode !== 'activity' && ' · your override will be applied on save'}</div>
            {check.issues.map((i, n) => <div key={n} className="text-xs text-slate-700">• {i.message}{i.booking_ids?.length ? ` (bookings ${i.booking_ids.map((x) => x.slice(0, 8)).join(', ')})` : ''}</div>)}
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Application name *" htmlFor="m-an"><input id="m-an" className="input" value={f.application_name} onChange={s('application_name')} /></Field>
          <Field label="Application version *" htmlFor="m-av"><input id="m-av" className="input" value={f.application_version} onChange={s('application_version')} /></Field>
          <Field label="PCI DSS scope *" htmlFor="m-pci"><select id="m-pci" className="input" value={f.pci} onChange={s('pci')}><option value="yes">Yes</option><option value="no">No</option></select></Field>
          <Field label="POC name *" htmlFor="m-pn"><input id="m-pn" className="input" value={f.poc_name} onChange={s('poc_name')} /></Field>
          <Field label="POC email *" htmlFor="m-pe"><input id="m-pe" type="email" className="input" value={f.poc_email} onChange={s('poc_email')} /></Field>
          <Field label="Comments" htmlFor="m-c"><input id="m-c" className="input" value={f.additional_comments} onChange={s('additional_comments')} /></Field>
        </div>
        <Field label="Reason / justification" htmlFor="m-r" hint="Recorded in the audit trail."><textarea id="m-r" className="input min-h-16" value={f.reason} onChange={s('reason')} /></Field>
        <div className="flex justify-end"><button className="btn-primary" disabled={!valid || busy}>{busy ? 'Saving…' : 'Create booking'}</button></div>
      </form>
      {force.dialog}
    </div>
  )
}
