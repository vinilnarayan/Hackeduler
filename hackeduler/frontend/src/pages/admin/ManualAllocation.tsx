import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, CheckCircle2 } from 'lucide-react'
import { get, post, validationMessage } from '../../api/client'
import type { ActivityType, AdminBooking, AvailabilityResult, ForcePayload, Product, ResourceAdmin } from '../../api/types'
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
  const products = useAsync<Product[]>(() => get('/api/admin/products'))
  const [f, setF] = useState({
    resource_id: sp.get('resource') ?? '', activity_type_id: '', start_date: sp.get('start') ?? '', additional_days: 0,
    duration_mode: 'activity' as 'activity' | 'duration', duration_days: 1, end_date: '',
    application_name: '', application_version: '', pci: 'no', poc_name: '', poc_email: '', additional_comments: '', reason: '',
    product_id: '', implementation_id: '',
  })
  const [check, setCheck] = useState<AvailabilityResult | null>(null)
  const [extras, setExtras] = useState<string[]>([])
  const [free, setFree] = useState<Record<string, AvailabilityResult>>({})
  const [busy, setBusy] = useState(false)
  const s = (k: keyof typeof f) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.type === 'number' ? parseInt(e.target.value || '0', 10) : e.target.value })

  const act = acts.data?.find((a) => a.id === f.activity_type_id)
  const needsRes = act?.requires_resource ?? true
  useEffect(() => {
    setCheck(null)
    if (!f.activity_type_id || !f.start_date || !needsRes) return
    const t = setTimeout(() => (f.resource_id
      ? post<AvailabilityResult>('/api/admin/availability/check', { resource_id: f.resource_id, activity_type_id: f.activity_type_id, start_date: f.start_date, additional_days: f.additional_days })
      : post<any>('/api/availability/auto', { activity_type_id: f.activity_type_id, start_date: f.start_date, additional_days: f.additional_days })
          .then((r) => ({ ...r, issues: [], message: r.available ? `Auto-assign: ${r.resource_display_name} (${r.available_resources} free)` : r.message }))
    ).then(setCheck).catch((e) => toast('error', validationMessage(e))), 250)
    return () => clearTimeout(t)
  }, [f.resource_id, f.activity_type_id, f.start_date, f.additional_days, needsRes])

  // Free / busy status of every other resource for the chosen activity and start date (multi-resource booking).
  useEffect(() => {
    setFree({})
    setExtras((x) => x.filter((id) => id !== f.resource_id))
    if (!f.resource_id || !needsRes || !f.activity_type_id || !f.start_date) return
    let live = true
    const t = setTimeout(() => {
      (resources.data ?? []).filter((r) => r.is_active && r.id !== f.resource_id).forEach((r) =>
        post<AvailabilityResult>('/api/admin/availability/check', { resource_id: r.id, activity_type_id: f.activity_type_id, start_date: f.start_date, additional_days: f.additional_days })
          .then((res) => { if (live) setFree((cur) => ({ ...cur, [r.id]: res })) }).catch(() => undefined))
    }, 300)
    return () => { live = false; clearTimeout(t) }
  }, [f.resource_id, f.activity_type_id, f.start_date, f.additional_days, needsRes, resources.data])

  const body = (fp?: ForcePayload) => ({
    resource_id: needsRes ? (f.resource_id || null) : null, activity_type_id: f.activity_type_id, start_date: f.start_date || null, additional_days: f.additional_days,
    product_id: f.product_id || null, implementation_id: f.implementation_id || null,
    duration_days: !f.end_date && f.duration_mode === 'duration' ? f.duration_days : null, end_date: f.end_date || null,
    additional_resource_ids: needsRes && f.resource_id ? extras : [], application_name: f.application_name, application_version: f.application_version,
    pci_dss_scope: f.pci === 'yes', poc_name: f.poc_name, poc_email: f.poc_email, additional_comments: f.additional_comments || null,
    reason: f.reason || null, ...(fp ? { force: fp } : {}),
  })
  const prod = products.data?.find((p) => p.id === f.product_id)
  const valid = f.activity_type_id && (!needsRes || f.start_date) && f.application_name && f.application_version && f.poc_name && f.poc_email
  return (
    <div className="max-w-5xl">
      <PageHeader title="Manual Allocation" subtitle="Create a booking directly, bypassing the requester workflow. If a conflict or restriction is detected you will be asked to confirm a Force Allocate." />
      <form className="card space-y-4 p-4" onSubmit={async (e) => {
        e.preventDefault(); setBusy(true)
        await force.run((fp) => post<AdminBooking>('/api/admin/bookings', body(fp)), (b) => { toast('success', `Booking ${b.id} created`); nav('/admin/bookings?q=' + b.id) })
        setBusy(false)
      }}>
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Activity type *" htmlFor="m-act"><select id="m-act" className="input" value={f.activity_type_id} onChange={s('activity_type_id')}><option value="">Select…</option>{acts.data?.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.name}{a.base_duration_days ? ` (${a.base_duration_days}d)` : ''}{a.requires_resource ? '' : ' – no resource'}{a.description && a.requires_resource ? ` – ${a.description}` : ''}</option>)}</select></Field>
          {needsRes ? <Field label="Resource" htmlFor="m-res" hint="Leave on auto to assign the best available engineer. Choose one to allocate (or force allocate) a specific engineer."><select id="m-res" className="input" value={f.resource_id} onChange={s('resource_id')}><option value="">Auto-assign best available</option>{resources.data?.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}{r.is_active ? '' : ' (inactive)'}</option>)}</select></Field>
            : <Field label="Resource" htmlFor="m-res"><input id="m-res" className="input" disabled value="Not required for this activity" /></Field>}
          <Field label={needsRes ? 'Start date *' : 'Date (optional)'} htmlFor="m-sd"><input id="m-sd" type="date" className="input" value={f.start_date} onChange={s('start_date')} /></Field>
          <Field label="End date (optional)" htmlFor="m-ed" hint="Leave empty to calculate the end date from the activity duration."><input id="m-ed" type="date" className="input" min={f.start_date || undefined} value={f.end_date} onChange={s('end_date')} /></Field>
          <Field label="Duration" htmlFor="m-dm" hint={f.end_date ? 'Not used while an end date is set.' : undefined}><select id="m-dm" className="input" disabled={!!f.end_date} value={f.duration_mode} onChange={s('duration_mode')}><option value="activity">From activity type</option><option value="duration">Override working days</option></select></Field>
          {!f.end_date && f.duration_mode === 'duration' && <Field label="Working days" htmlFor="m-dd"><input id="m-dd" type="number" min={1} max={250} className="input" value={f.duration_days} onChange={s('duration_days')} /></Field>}
          {act?.allow_additional_days && f.duration_mode === 'activity' && <Field label="Additional days" htmlFor="m-ad"><input id="m-ad" type="number" min={0} max={act.max_additional_days} className="input" value={f.additional_days} onChange={s('additional_days')} /></Field>}
        </div>
        <p className="text-xs text-slate-500">Manual allocations need no approval: the booking is confirmed straight away and the POC (and the engineer) are notified.</p>
        {needsRes && f.resource_id && f.activity_type_id && f.start_date && (
          <fieldset className="rounded-md border border-slate-200 p-3">
            <legend className="px-1 text-sm font-medium">Also block other resources for this booking (optional)</legend>
            <p className="mb-2 text-xs text-slate-500">All selected resources are reserved together in one confirmed booking. Only resources that are free for the whole period can be added.</p>
            <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
              {(resources.data ?? []).filter((r) => r.is_active && r.id !== f.resource_id).map((r) => {
                const st = free[r.id]
                const busy = !!st && !st.available
                return (
                  <label key={r.id} className={`flex items-start gap-2 rounded border border-slate-200 p-2 text-sm ${busy ? 'opacity-60' : ''}`} title={busy ? st.message : undefined}>
                    <input type="checkbox" className="mt-0.5" disabled={busy || !st} checked={extras.includes(r.id)}
                      onChange={(e) => setExtras(e.target.checked ? [...extras, r.id] : extras.filter((x) => x !== r.id))} />
                    <span className="flex-1">{r.display_name} – {r.engineer_name}</span>
                    <span className={`text-xs font-medium ${!st ? 'text-slate-400' : busy ? 'text-amber-700' : 'text-emerald-700'}`}>{!st ? '…' : busy ? 'Busy' : 'Free'}</span>
                  </label>
                )
              })}
            </div>
            {extras.length > 0 && <p className="mt-2 text-xs text-slate-600">{extras.length + 1} resources will be blocked. Force Allocate is not available for multi-resource bookings.</p>}
          </fieldset>
        )}
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
          <Field label="Product" htmlFor="m-prod"><select id="m-prod" className="input" value={f.product_id} onChange={(e) => setF({ ...f, product_id: e.target.value, implementation_id: '' })}><option value="">— None —</option>{products.data?.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Implementation" htmlFor="m-impl"><select id="m-impl" className="input" value={f.implementation_id} disabled={!prod} onChange={s('implementation_id')}><option value="">— None —</option>{prod?.implementations.filter((i) => i.is_active).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></Field>
        </div>
        <Field label="Reason / justification" htmlFor="m-r" hint="Recorded in the audit trail."><textarea id="m-r" className="input min-h-16" value={f.reason} onChange={s('reason')} /></Field>
        <div className="flex justify-end"><button className="btn-primary" disabled={!valid || busy}>{busy ? 'Saving…' : 'Create booking'}</button></div>
      </form>
      {force.dialog}
    </div>
  )
}
