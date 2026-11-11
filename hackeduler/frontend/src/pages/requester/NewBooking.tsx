import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, CheckCircle2, Info, Loader2, Sparkles } from 'lucide-react'
import { ApiError, get, post, validationMessage } from '../../api/client'
import type { ActivityType, Booking } from '../../api/types'
import { Field, PageHeader } from '../../components/ui'
import { fmt } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

interface AutoResult {
  available: boolean
  requires_resource: boolean
  resource_display_name: string | null
  duration_days: number | null
  start_date: string | null
  end_date: string | null
  work_dates: string[]
  reason: string | null
  message: string
  suggested_start_date: string | null
  available_resources: number
}

interface MyImpls { product: { id: string; name: string } | null; implementations: { id: string; name: string }[]; default_implementation_id: string | null }

/**
 * Requesters choose WHAT (activity) and WHEN (start date); the server picks the security resource
 * (earliest finish, then lightest workload). Admins can reassign the resource later.
 */
import { validPocEmails } from '../../lib/emails'

export default function NewBooking() {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const toast = useToast()
  const acts = useAsync<ActivityType[]>(() => get('/api/activity-types'))
  const mine = useAsync<MyImpls>(() => get('/api/me/implementations'))
  const [activityId, setActivityId] = useState('')
  const [start, setStart] = useState(sp.get('start') ?? '')
  const [extra, setExtra] = useState(0)
  const [implementationId, setImplementationId] = useState('')
  const [check, setCheck] = useState<AutoResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [checkErr, setCheckErr] = useState<string | null>(null)
  const [form, setForm] = useState({ application_name: '', application_version: '', pci_dss_scope: '' as '' | 'yes' | 'no', poc_name: '', poc_email: '', additional_comments: '' })
  const [submitting, setSubmitting] = useState(false)
  const [submitErr, setSubmitErr] = useState<string | null>(null)
  const activity = useMemo(() => acts.data?.find((a) => a.id === activityId), [acts.data, activityId])
  const needsResource = activity?.requires_resource ?? true

  useEffect(() => { if (mine.data?.default_implementation_id && !implementationId) setImplementationId(mine.data.default_implementation_id) }, [mine.data])

  const runCheck = async () => {
    setChecking(true); setCheckErr(null)
    try { setCheck(await post<AutoResult>('/api/availability/auto', { activity_type_id: activityId, start_date: start || null, additional_days: extra })) }
    catch (e) { setCheckErr(validationMessage(e)) } finally { setChecking(false) }
  }
  useEffect(() => {
    setCheck(null); setCheckErr(null)
    if (!activityId || (needsResource && !start)) return
    const t = setTimeout(runCheck, 250)
    return () => clearTimeout(t)
  }, [activityId, start, extra])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value })
  const formValid = form.application_name.trim() && form.application_version.trim() && form.pci_dss_scope && form.poc_name.trim() && validPocEmails(form.poc_email)
  const ready = !!check?.available

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true); setSubmitErr(null)
    try {
      const b = await post<Booking>('/api/bookings', {
        application_name: form.application_name, application_version: form.application_version, activity_type_id: activityId,
        pci_dss_scope: form.pci_dss_scope === 'yes', start_date: start || null, poc_name: form.poc_name,
        poc_email: form.poc_email, additional_comments: form.additional_comments || null, additional_days: extra,
        implementation_id: implementationId || null,
      })
      toast('success', `Booking request ${b.id} submitted`)
      nav(`/bookings/${b.id}/confirmation`)
    } catch (err) {
      setSubmitErr(validationMessage(err))
      if (err instanceof ApiError && err.status === 409) { toast('error', err.message); runCheck() }
    } finally { setSubmitting(false) }
  }

  return (
    <div className="max-w-4xl space-y-4">
      <PageHeader title="New Booking Request" subtitle="Choose the activity and a start date. A free security resource is assigned automatically and the expected end date is calculated from working days." />
      <section className="card space-y-4 p-4" aria-labelledby="slot-h">
        <h2 id="slot-h" className="text-sm font-semibold">1. Activity and dates</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Activity type *" htmlFor="act">
            <select id="act" className="input" value={activityId} onChange={(e) => { setActivityId(e.target.value); setExtra(0) }}>
              <option value="">Select an activity…</option>
              {(acts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}{a.base_duration_days ? ` – ${a.base_duration_days} working days` : ''}{!a.requires_resource ? ' (no resource needed)' : ''}{a.description && a.requires_resource ? ` (${a.description})` : ''}</option>)}
            </select>
          </Field>
          <Field label={needsResource ? 'Proposed start date *' : 'Preferred date (optional)'} htmlFor="start" hint={needsResource ? 'Must be a working day.' : 'Leave empty if the date is flexible.'}>
            <input id="start" type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          {activity?.allow_additional_days && (
            <Field label="Additional working days" htmlFor="extra" hint={`Optional, up to ${activity.max_additional_days}.`}>
              <input id="extra" type="number" min={0} max={activity.max_additional_days} className="input" value={extra}
                onChange={(e) => setExtra(Math.max(0, Math.min(activity.max_additional_days, parseInt(e.target.value || '0', 10))))} />
            </Field>
          )}
          {mine.data?.product && (
            <Field label="Implementation" htmlFor="impl" hint={`Product: ${mine.data.product.name}`}>
              <select id="impl" className="input" value={implementationId} onChange={(e) => setImplementationId(e.target.value)}>
                <option value="">— Not specific —</option>
                {mine.data.implementations.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
              </select>
            </Field>
          )}
        </div>

        <div aria-live="polite">
          {checking && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Checking availability…</div>}
          {checkErr && <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{checkErr}</div>}
          {check && check.available && check.requires_resource && (
            <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm">
              <div className="flex items-center gap-2 font-semibold text-emerald-800"><CheckCircle2 className="h-4 w-4" /> A security resource is available</div>
              <div className="mt-2 grid gap-2 sm:grid-cols-4">
                <div><div className="text-xs text-slate-500">Assigned resource</div><div className="font-medium">{check.resource_display_name}</div></div>
                <div><div className="text-xs text-slate-500">Start date</div><div className="font-medium">{fmt(check.start_date)}</div></div>
                <div><div className="text-xs text-slate-500">Expected end date</div><div className="font-medium">{fmt(check.end_date)}</div></div>
                <div><div className="text-xs text-slate-500">Duration</div><div className="font-medium">{check.duration_days} working days</div></div>
              </div>
              <p className="mt-2 text-xs text-slate-600">Weekends, organisation holidays and resource leave are excluded. The OffSec team may assign a different engineer when approving.</p>
            </div>
          )}
          {check && check.available && !check.requires_resource && (
            <div className="flex gap-2 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              <div>{check.message}{check.start_date && <> Planned: {fmt(check.start_date)}{check.end_date && check.end_date !== check.start_date ? ` – ${fmt(check.end_date)}` : ''}.</>}</div>
            </div>
          )}
          {check && !check.available && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
              <div className="flex items-center gap-2 font-semibold text-amber-900"><AlertCircle className="h-4 w-4" /> Not available</div>
              <p className="mt-1">{check.message}</p>
              {check.suggested_start_date && (
                <button type="button" className="btn-secondary mt-3" onClick={() => setStart(check.suggested_start_date!)}>
                  <Sparkles className="h-4 w-4 text-amber-600" /> Use next available date: {fmt(check.suggested_start_date)}
                </button>
              )}
            </div>
          )}
        </div>
      </section>

      <form className={`card space-y-4 p-4 ${ready ? '' : 'pointer-events-none opacity-50'}`} onSubmit={submit} aria-disabled={!ready}>
        <h2 className="text-sm font-semibold">2. Booking details</h2>
        <fieldset disabled={!ready} className="grid gap-4 md:grid-cols-2">
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
          <Field label="POC email *" htmlFor="pe" hint="You can enter several addresses, separated by commas." error={form.poc_email && !validPocEmails(form.poc_email) ? 'Enter valid email addresses (up to 10), separated by commas' : undefined}>
            <input id="pe" type="text" inputMode="email" className="input" maxLength={2000} placeholder="name@company.com, other@company.com" value={form.poc_email} onChange={set('poc_email')} required />
          </Field>
          <div className="md:col-span-2"><Field label="Additional comments" htmlFor="ac"><textarea id="ac" className="input min-h-20" maxLength={4000} value={form.additional_comments} onChange={set('additional_comments')} /></Field></div>
        </fieldset>
        {submitErr && <div className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800" role="alert">{submitErr}</div>}
        <div className="flex justify-end"><button className="btn-primary" disabled={!ready || !formValid || submitting}>{submitting ? 'Submitting…' : 'Submit booking request'}</button></div>
      </form>
    </div>
  )
}
