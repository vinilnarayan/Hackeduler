import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, CheckCircle2, Loader2, Sparkles } from 'lucide-react'
import { ApiError, get, post, validationMessage } from '../../api/client'
import type { ActivityType, AvailabilityResult, Booking, ResourcePublic } from '../../api/types'
import { Field, PageHeader } from '../../components/ui'
import { fmt } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function NewBooking() {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const toast = useToast()
  const resources = useAsync<ResourcePublic[]>(() => get('/api/resources'))
  const acts = useAsync<ActivityType[]>(() => get('/api/activity-types'))
  const [resourceId, setResourceId] = useState(sp.get('resource') ?? '')
  const [activityId, setActivityId] = useState('')
  const [start, setStart] = useState(sp.get('start') ?? '')
  const [extra, setExtra] = useState(0)
  const [check, setCheck] = useState<AvailabilityResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [checkErr, setCheckErr] = useState<string | null>(null)
  const [form, setForm] = useState({ application_name: '', application_version: '', pci_dss_scope: '' as '' | 'yes' | 'no', poc_name: '', poc_email: '', additional_comments: '' })
  const [submitting, setSubmitting] = useState(false)
  const [submitErr, setSubmitErr] = useState<string | null>(null)
  const activity = useMemo(() => acts.data?.find((a) => a.id === activityId), [acts.data, activityId])
  const active = (resources.data ?? []).filter((r) => r.is_active)

  // Step 2-5: backend-authoritative availability + end-date calculation
  useEffect(() => {
    setCheck(null); setCheckErr(null)
    if (!resourceId || !activityId || !start) return
    const t = setTimeout(async () => {
      setChecking(true)
      try {
        setCheck(await post<AvailabilityResult>('/api/availability/check', { resource_id: resourceId, activity_type_id: activityId, start_date: start, additional_days: extra }))
      } catch (e) { setCheckErr(validationMessage(e)) } finally { setChecking(false) }
    }, 250)
    return () => clearTimeout(t)
  }, [resourceId, activityId, start, extra])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value })
  const formValid = form.application_name.trim() && form.application_version.trim() && form.pci_dss_scope && form.poc_name.trim() && /^\S+@\S+\.\S+$/.test(form.poc_email)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true); setSubmitErr(null)
    try {
      const b = await post<Booking>('/api/bookings', {
        application_name: form.application_name, application_version: form.application_version, activity_type_id: activityId,
        pci_dss_scope: form.pci_dss_scope === 'yes', resource_id: resourceId, start_date: start, poc_name: form.poc_name,
        poc_email: form.poc_email, additional_comments: form.additional_comments || null, additional_days: extra,
      })
      toast('success', `Booking request ${b.id} submitted`)
      nav(`/bookings/${b.id}/confirmation`)
    } catch (err) {
      setSubmitErr(validationMessage(err))
      if (err instanceof ApiError && err.status === 409) {
        toast('error', err.message)
        setCheck(null)
        post<AvailabilityResult>('/api/availability/check', { resource_id: resourceId, activity_type_id: activityId, start_date: start, additional_days: extra }).then(setCheck).catch(() => {})
      }
    } finally { setSubmitting(false) }
  }

  return (
    <div className="max-w-4xl space-y-4">
      <PageHeader title="New Booking Request" subtitle="Choose a resource, activity and start date. The expected end date is calculated by the server from working days." />
      <section className="card space-y-4 p-4" aria-labelledby="slot-h">
        <h2 id="slot-h" className="text-sm font-semibold">1. Select slot</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Resource *" htmlFor="res">
            <select id="res" className="input" value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
              <option value="">Select a resource…</option>
              {active.map((r) => <option key={r.id} value={r.id}>{r.display_name}</option>)}
            </select>
          </Field>
          <Field label="Activity type *" htmlFor="act">
            <select id="act" className="input" value={activityId} onChange={(e) => { setActivityId(e.target.value); setExtra(0) }}>
              <option value="">Select an activity…</option>
              {(acts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} – {a.base_duration_days} working days{a.description ? ` (${a.description})` : ''}</option>)}
            </select>
          </Field>
          <Field label="Proposed start date *" htmlFor="start" hint="Must be a working day for the selected resource.">
            <input id="start" type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          {activity?.allow_additional_days && (
            <Field label="Additional working days" htmlFor="extra" hint={`Optional, up to ${activity.max_additional_days}.`}>
              <input id="extra" type="number" min={0} max={activity.max_additional_days} className="input" value={extra}
                onChange={(e) => setExtra(Math.max(0, Math.min(activity.max_additional_days, parseInt(e.target.value || '0', 10))))} />
            </Field>
          )}
        </div>

        <div aria-live="polite">
          {checking && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Checking availability…</div>}
          {checkErr && <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{checkErr}</div>}
          {check && check.available && (
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm">
              <div className="flex items-center gap-2 font-semibold text-emerald-800"><CheckCircle2 className="h-4 w-4" /> {check.resource_display_name} is available</div>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <div><div className="text-xs text-slate-500">Start date</div><div className="font-medium">{fmt(check.start_date)}</div></div>
                <div><div className="text-xs text-slate-500">Expected end date</div><div className="font-medium">{fmt(check.end_date)}</div></div>
                <div><div className="text-xs text-slate-500">Duration</div><div className="font-medium">{check.duration_days} working days</div></div>
              </div>
              <p className="mt-2 text-xs text-slate-600">Weekends, organisation holidays and resource leave are excluded. Reserved working days: {check.work_dates.map((d) => fmt(d, 'dd MMM')).join(', ')}</p>
            </div>
          )}
          {check && !check.available && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
              <div className="flex items-center gap-2 font-semibold text-amber-900"><AlertCircle className="h-4 w-4" /> Not available</div>
              <p className="mt-1">{check.message}</p>
              {check.issues.length > 1 && <ul className="mt-1 list-disc pl-5 text-xs">{check.issues.slice(1).map((i, n) => <li key={n}>{i.message}</li>)}</ul>}
              <div className="mt-3 flex flex-wrap gap-2">
                {check.suggested_start_date && (
                  <button type="button" className="btn-secondary" onClick={() => setStart(check.suggested_start_date!)}>
                    <Sparkles className="h-4 w-4 text-amber-600" /> Use next available date: {fmt(check.suggested_start_date)}
                  </button>
                )}
                {check.alternative_resources.map((r) => (
                  <button type="button" key={r.id} className="btn-secondary" onClick={() => setResourceId(r.id)}>Use {r.display_name} on {fmt(start)}</button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      <form className={`card space-y-4 p-4 ${check?.available ? '' : 'pointer-events-none opacity-50'}`} onSubmit={submit} aria-disabled={!check?.available}>
        <h2 className="text-sm font-semibold">2. Booking details</h2>
        <fieldset disabled={!check?.available} className="grid gap-4 md:grid-cols-2">
          <Field label="Application name *" htmlFor="an"><input id="an" className="input" maxLength={255} value={form.application_name} onChange={set('application_name')} required /></Field>
          <Field label="Application version *" htmlFor="av"><input id="av" className="input" maxLength={100} value={form.application_version} onChange={set('application_version')} required /></Field>
          <fieldset>
            <legend className="label">PCI DSS scope *</legend>
            <div className="flex gap-4 pt-1 text-sm">
              {(['yes', 'no'] as const).map((v) => (
                <label key={v} className="flex items-center gap-1.5"><input type="radio" name="pci" value={v} checked={form.pci_dss_scope === v} onChange={() => setForm({ ...form, pci_dss_scope: v })} />{v === 'yes' ? 'Yes' : 'No'}</label>
              ))}
            </div>
          </fieldset>
          <div />
          <Field label="POC name *" htmlFor="pn"><input id="pn" className="input" maxLength={255} value={form.poc_name} onChange={set('poc_name')} required /></Field>
          <Field label="POC email *" htmlFor="pe" error={form.poc_email && !/^\S+@\S+\.\S+$/.test(form.poc_email) ? 'Enter a valid email address' : undefined}>
            <input id="pe" type="email" className="input" maxLength={254} value={form.poc_email} onChange={set('poc_email')} required />
          </Field>
          <div className="md:col-span-2"><Field label="Additional comments" htmlFor="ac"><textarea id="ac" className="input min-h-20" maxLength={4000} value={form.additional_comments} onChange={set('additional_comments')} /></Field></div>
        </fieldset>
        {submitErr && <div className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800" role="alert">{submitErr}</div>}
        <div className="flex justify-end"><button className="btn-primary" disabled={!check?.available || !formValid || submitting}>{submitting ? 'Submitting…' : 'Submit booking request'}</button></div>
      </form>
    </div>
  )
}
