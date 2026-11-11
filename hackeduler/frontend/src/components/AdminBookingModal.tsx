import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Pencil, Trash2, X } from 'lucide-react'
import { get, patch, post, validationMessage } from '../api/client'
import type { ActivityType, AdminBooking, AuditEntry, ForcePayload, Product, ResourceAdmin } from '../api/types'
import { fmt, fmtDateTime } from '../lib/dates'
import { CONFLICT_TYPE_LABELS, STATUS_LABELS } from '../lib/status'
import { useToast } from '../lib/toast'
import { useAsync } from '../lib/useAsync'
import { ConfirmDialog } from './ConfirmDialog'
import { useForceFlow } from './useForceFlow'
import { ErrorState, Field, KV, Modal, Pill, Spinner, StatusBadge } from './ui'

export function AuditChanges({ a }: { a: AuditEntry }) {
  const prev = a.previous_value ?? {}
  const next = a.new_value ?? {}
  const keys = Array.from(new Set([...Object.keys(prev || {}), ...Object.keys(next || {})])).filter((k) => JSON.stringify(prev?.[k]) !== JSON.stringify(next?.[k]))
  if (!keys.length) return null
  return (
    <table className="mt-1 w-full text-xs">
      <tbody>
        {keys.slice(0, 30).map((k) => (
          <tr key={k} className="align-top"><td className="pr-2 font-medium text-slate-600">{k}</td>
            <td className="pr-2 break-all text-red-700 line-through decoration-red-300">{fmtVal(prev?.[k])}</td>
            <td className="break-all text-emerald-700">{fmtVal(next?.[k])}</td></tr>
        ))}
      </tbody>
    </table>
  )
}
const fmtVal = (v: any) => (v === undefined || v === null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v))

function InitiationStatus({ b, onSent }: { b: AdminBooking; onSent: () => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const i = b.initiation_email
  if (!i) return <>—</>
  const text = i.state === 'sent' ? `Sent ${fmtDateTime(i.sent_at)}`
    : i.state === 'scheduled' ? `Will be sent on ${fmt(i.scheduled_for)} (${i.days_before} day${i.days_before === 1 ? '' : 's'} before the start date)`
    : i.state === 'disabled' ? 'Automatic sending is turned off for this booking' : (i.note || 'Not applicable')
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span>{text}</span>
      {i.can_send && <button type="button" className="btn-secondary" disabled={busy}
        onClick={async () => { setBusy(true); try { await post(`/api/admin/bookings/${b.id}/send-initiation-email`, {}); toast('success', 'Initiation email queued'); onSent() } catch (e) { toast('error', validationMessage(e)) } finally { setBusy(false) } }}>
        {busy ? 'Sending…' : i.state === 'sent' ? 'Resend initiation email' : 'Send initiation email now'}</button>}
    </span>
  )
}

export function AdminBookingModal({ bookingId, onClose, onChanged }: { bookingId: string; onClose: () => void; onChanged?: () => void }) {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<any>(() => get(`/api/admin/bookings/${bookingId}`), [bookingId])
  const [tab, setTab] = useState<'overview' | 'edit' | 'audit' | 'conflicts' | 'emails'>('overview')
  const [dlg, setDlg] = useState<null | 'approve' | 'reject' | 'cancel' | 'complete'>(null)
  const force = useForceFlow()
  const changed = () => { reload(); onChanged?.() }

  if (error) return <Modal open onClose={onClose} title="Booking"><ErrorState message={error} onRetry={reload} /></Modal>
  if (loading || !data) return <Modal open onClose={onClose} title="Booking"><Spinner /></Modal>
  const b: AdminBooking = data.booking
  const active = b.status === 'pending_approval' || b.status === 'approved'

  const approve = () => force.run((f?: ForcePayload) => post(`/api/admin/bookings/${b.id}/approve`, f ? { force: f } : {}), () => { toast('success', 'Booking approved; POC notified'); setDlg(null); changed() })

  const tabs = [['overview', 'Overview'], ['edit', 'Modify / Reassign'], ['audit', `Audit (${data.audit.length})`], ['conflicts', `Conflicts (${data.conflicts.length})`], ['emails', `Emails (${data.emails.length})`]] as const
  return (
    <Modal open onClose={onClose} size="xl" title={<span className="flex flex-wrap items-center gap-2">{b.application_name} <StatusBadge status={b.status} />{b.is_force_allocated && <Pill className="bg-red-100 text-red-800">Force allocated</Pill>}{b.needs_review && <Pill className="bg-amber-100 text-amber-800"><AlertTriangle className="h-3 w-3" />Needs review</Pill>}</span>}
      footer={<>
        {b.status === 'pending_approval' && <><button className="btn-success" onClick={() => setDlg('approve')}><Check className="h-4 w-4" />Approve</button><button className="btn-danger" onClick={() => setDlg('reject')}><X className="h-4 w-4" />Reject</button></>}
        {b.status === 'approved' && !b.requires_resource && <button className="btn-success" onClick={() => setDlg('complete')}><Check className="h-4 w-4" />Mark completed</button>}
        {active && <button className="btn-secondary" onClick={() => setDlg('cancel')}><Trash2 className="h-4 w-4" />Cancel booking</button>}
        {active && <button className="btn-secondary" onClick={() => setTab('edit')}><Pencil className="h-4 w-4" />Modify</button>}
      </>}>
      <div className="mb-3 flex flex-wrap gap-1 border-b border-slate-200" role="tablist">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${tab === k ? 'border-blue-700 font-medium text-blue-800' : 'border-transparent text-slate-600 hover:text-slate-900'}`}>{l}</button>)}
      </div>
      {tab === 'overview' && (
        <div className="space-y-4">
          <KV items={[
            ['Booking ID', <span className="font-mono text-xs break-all">{b.id}</span>], ['Status', STATUS_LABELS[b.status]],
            ['Application', `${b.application_name} v${b.application_version}`], ['PCI DSS scope', b.pci_dss_scope ? 'Yes' : 'No'],
            ['Activity type', b.duration_days ? `${b.activity_name} (${b.duration_days} working days${b.duration_overridden ? ', overridden' : ''}${b.base_duration_snapshot ? `; snapshot base ${b.base_duration_snapshot}` : ''})` : b.activity_name],
            ['Resource', b.requires_resource ? `${b.resource_display_name} (${b.resource_code})` : 'Not required for this activity'],
            ['Assigned engineer', b.requires_resource ? <span className="font-medium">{b.engineer_name}</span> : '—'],
            ...(b.extra_resources?.length ? [['Additional resources', <span className="font-medium">{b.extra_resources.map((r) => `${r.display_name} (${r.engineer_name})`).join(', ')}</span>] as [string, React.ReactNode]] : []),
            ['Product', b.product_name ?? '—'], ['Implementation', b.implementation_name ?? '—'],
            ['Start date', fmt(b.start_date)], ['Expected end date', fmt(b.end_date)],
            ['POC', `${b.poc_name} <${b.poc_email}>`], ['Requester', `${b.requester_name} <${b.requester_email}>`],
            ['Source', b.source === 'admin' ? 'Admin-created' : 'Requester'], ['Submitted', fmtDateTime(b.submitted_at)],
            ['Approved at', fmtDateTime(b.approved_at)], ['Pending expiry', b.status === 'pending_approval' ? fmtDateTime(b.expires_at) : '—'],
            ['Initiation email', <InitiationStatus b={b} onSent={changed} />],
            ...(b.rejection_reason ? [['Rejection reason', b.rejection_reason] as [string, string]] : []),
            ...(b.cancellation_reason ? [['Cancellation reason', b.cancellation_reason] as [string, string]] : []),
            ...(b.additional_comments ? [['Comments', b.additional_comments] as [string, string]] : []),
          ]} />
          {b.pending_change_request && <div className="rounded border border-amber-300 bg-amber-50 p-2 text-sm">Pending requester {b.pending_change_request.request_type} request: “{b.pending_change_request.reason}”{b.pending_change_request.proposed_start_date ? ` → start ${fmt(b.pending_change_request.proposed_start_date)}` : ''}. Review it under Change Requests.</div>}
          <div>
            <div className="label">Status history</div>
            <ul className="space-y-1 text-sm">{data.status_history.map((h: any, i: number) => <li key={i} className="flex flex-wrap gap-2"><span className="text-xs text-slate-500">{fmtDateTime(h.changed_at)}</span><span>{h.from_status ? `${STATUS_LABELS[h.from_status as keyof typeof STATUS_LABELS]} → ` : ''}<b>{STATUS_LABELS[h.to_status as keyof typeof STATUS_LABELS]}</b></span><span className="text-xs text-slate-500">by {h.changed_by}</span>{h.reason && <span className="text-xs text-slate-600">– {h.reason}</span>}</li>)}</ul>
          </div>
          <div>
            <div className="label">Reserved working days</div>
            <div className="flex flex-wrap gap-1">{data.locks.filter((l: any) => l.lock_status !== 'released').map((l: any) => <Pill key={l.work_date + l.resource_id} className={l.is_forced ? 'bg-red-100 text-red-800' : l.lock_status === 'confirmed' ? 'bg-emerald-100 text-emerald-800' : 'bg-blue-100 text-blue-800'}>{fmt(l.work_date, 'dd MMM')}{l.is_forced ? ' (forced)' : ''}</Pill>)}</div>
          </div>
        </div>
      )}
      {tab === 'edit' && (active ? <EditBooking b={b} run={force.run} onSaved={() => { toast('success', 'Booking updated'); setTab('overview'); changed() }} /> : <p className="text-sm text-slate-500">Only pending or approved bookings can be modified.</p>)}
      {tab === 'audit' && (
        <ol className="space-y-3">{data.audit.slice().reverse().map((a: AuditEntry) => (
          <li key={a.id} className="rounded border border-slate-200 p-2 text-sm">
            <div className="flex flex-wrap items-center gap-2"><Pill className={a.action.includes('force') ? 'bg-red-100 text-red-800' : 'bg-slate-100 text-slate-700'}>{a.action}</Pill><span className="text-xs text-slate-500">{fmtDateTime(a.created_at)} · {a.actor_email} ({a.actor_role})</span></div>
            {a.reason && <div className="mt-1 text-xs"><b>Reason:</b> {a.reason}</div>}
            <AuditChanges a={a} />
          </li>
        ))}</ol>
      )}
      {tab === 'conflicts' && (data.conflicts.length === 0 ? <p className="text-sm text-slate-500">No conflicts recorded for this booking.</p> : (
        <ul className="space-y-2">{data.conflicts.map((c: any) => (
          <li key={c.id} className="rounded border border-slate-200 p-2 text-sm"><div className="flex flex-wrap gap-2"><Pill className={c.status === 'open' ? 'bg-red-100 text-red-800' : 'bg-emerald-100 text-emerald-800'}>{c.status}</Pill><Pill>{CONFLICT_TYPE_LABELS[c.conflict_type]}</Pill><span className="text-xs text-slate-500">{fmtDateTime(c.created_at)}</span></div><div className="mt-1">{c.description}</div>{c.resolution_note && <div className="text-xs text-emerald-800">Resolution: {c.resolution_note}</div>}</li>
        ))}</ul>
      ))}
      {tab === 'emails' && (
        <table className="min-w-full text-sm"><thead><tr><th className="th">Template</th><th className="th">Recipient</th><th className="th">Status</th><th className="th">Created</th></tr></thead>
          <tbody>{data.emails.map((e: any) => <tr key={e.id}><td className="td">{e.template_key}</td><td className="td">{e.recipient}</td><td className="td">{e.status}{e.last_error && <div className="text-xs text-red-700">{e.last_error}</div>}</td><td className="td text-xs">{fmtDateTime(e.created_at)}</td></tr>)}</tbody></table>
      )}

      <ConfirmDialog open={dlg === 'approve'} title="Approve booking" tone="success" confirmLabel="Approve" onClose={() => setDlg(null)}
        message={<>Availability will be revalidated on the server. If the reservation is no longer valid you will be shown the conflict. Approve <b>{b.application_name}</b>{b.requires_resource ? <> on {b.resource_display_name} ({fmt(b.start_date)} – {fmt(b.end_date)})</> : ' (no security resource needed)'}?</>}
        onConfirm={async () => { setDlg(null); await approve() }} />
      <ConfirmDialog open={dlg === 'reject'} title="Reject booking" tone="danger" confirmLabel="Reject" requireReason reasonLabel="Rejection reason (sent to the POC)" onClose={() => setDlg(null)}
        message="The temporary reservation will be released and the POC notified with the reason."
        onConfirm={async (reason) => { try { await post(`/api/admin/bookings/${b.id}/reject`, { reason }); toast('success', 'Booking rejected; POC notified'); setDlg(null); changed() } catch (e) { toast('error', validationMessage(e)) } }} />
      <ConfirmDialog open={dlg === 'cancel'} title="Cancel booking" tone="danger" confirmLabel="Cancel booking" requireReason reasonLabel="Cancellation reason" onClose={() => setDlg(null)}
        message={b.status === 'approved' ? 'This is an approved booking. The POC will be notified and the resource released.' : 'The pending reservation will be released.'}
        onConfirm={async (reason) => { try { await post(`/api/admin/bookings/${b.id}/cancel`, { reason }); toast('success', 'Booking cancelled'); setDlg(null); changed() } catch (e) { toast('error', validationMessage(e)) } }} />
      <ConfirmDialog open={dlg === 'complete'} title="Mark completed" tone="success" confirmLabel="Mark completed" requireReason={false} reasonLabel="Note (optional)" onClose={() => setDlg(null)}
        message="Confirm that this activity has been carried out."
        onConfirm={async (note) => { try { await post(`/api/admin/bookings/${b.id}/complete`, { note: note || null }); toast('success', 'Booking marked completed'); setDlg(null); changed() } catch (e) { toast('error', validationMessage(e)) } }} />
      {force.dialog}
    </Modal>
  )
}

function EditBooking({ b, run, onSaved }: { b: AdminBooking; run: ReturnType<typeof useForceFlow>['run']; onSaved: () => void }) {
  const resources = useAsync<ResourceAdmin[]>(() => get('/api/admin/resources'))
  const acts = useAsync<ActivityType[]>(() => get('/api/admin/activity-types?include_deleted=true'))
  const products = useAsync<Product[]>(() => get('/api/admin/products'))
  const [f, setF] = useState({
    resource_id: b.resource_id ?? '', start_date: b.start_date ?? '', activity_type_id: b.activity_type_id, additional_days: b.additional_days,
    duration_mode: 'keep' as 'keep' | 'recalculate' | 'duration' | 'end_date', duration_days: b.duration_days ?? 1, end_date: b.end_date ?? '',
    product_id: b.product_id ?? '', implementation_id: b.implementation_id ?? '',
    application_name: b.application_name, application_version: b.application_version, pci: b.pci_dss_scope, poc_name: b.poc_name,
    poc_email: b.poc_email, additional_comments: b.additional_comments ?? '', reason: '',
  })
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (f.activity_type_id !== b.activity_type_id && f.duration_mode === 'keep') setF((x) => ({ ...x, duration_mode: 'recalculate' })) }, [f.activity_type_id])
  const s = (k: keyof typeof f) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.type === 'number' ? parseInt(e.target.value || '0', 10) : e.target.value })

  function body(force?: ForcePayload) {
    const out: Record<string, any> = { reason: f.reason }
    if (f.resource_id && f.resource_id !== b.resource_id && act?.requires_resource !== false) out.resource_id = f.resource_id
    if (f.start_date && f.start_date !== b.start_date) out.start_date = f.start_date
    if ((f.product_id || null) !== b.product_id) out.product_id = f.product_id || null
    if ((f.implementation_id || null) !== b.implementation_id) out.implementation_id = f.implementation_id || null
    if (f.activity_type_id !== b.activity_type_id) out.activity_type_id = f.activity_type_id
    if (f.additional_days !== b.additional_days) out.additional_days = f.additional_days
    if (f.duration_mode === 'recalculate') out.recalculate = true
    if (f.duration_mode === 'duration') out.duration_days = f.duration_days
    if (f.duration_mode === 'end_date') out.end_date = f.end_date
    for (const [k, bk] of [['application_name', 'application_name'], ['application_version', 'application_version'], ['poc_name', 'poc_name'], ['poc_email', 'poc_email']] as const)
      if ((f as any)[k] !== (b as any)[bk]) out[k] = (f as any)[k]
    if (f.pci !== b.pci_dss_scope) out.pci_dss_scope = f.pci
    if ((f.additional_comments || null) !== (b.additional_comments || null)) out.additional_comments = f.additional_comments || null
    if (force) out.force = force
    return out
  }
  const act = acts.data?.find((a) => a.id === f.activity_type_id)
  const needsRes = act?.requires_resource ?? b.requires_resource
  const prod = products.data?.find((p) => p.id === f.product_id)
  return (
    <form className="space-y-4" onSubmit={async (e) => { e.preventDefault(); setBusy(true); await run((force) => patch(`/api/admin/bookings/${b.id}`, body(force)), onSaved); setBusy(false) }}>
      <p className="text-xs text-slate-500">All changes are revalidated on the server, audited with previous values, and notify the POC if the booking is approved. The old reservation is only released when the new allocation commits.</p>
      <div className="grid gap-3 md:grid-cols-3">
        {b.extra_resources?.length > 0 && <div className="col-span-full rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">This booking holds {b.extra_resources.length + 1} resources, so its dates, activity and resources can’t be changed here – only the details. To change them, cancel it and create a new multi-resource booking.</div>}
        <Field label="Activity type" htmlFor="e-act"><select id="e-act" className="input" value={f.activity_type_id} onChange={s('activity_type_id')}>{acts.data?.filter((a) => !a.deleted_at || a.id === b.activity_type_id).map((a) => <option key={a.id} value={a.id} disabled={(!a.is_active || !!a.deleted_at) && a.id !== b.activity_type_id}>{a.name}{a.base_duration_days ? ` (${a.base_duration_days}d)` : ''}{a.requires_resource ? '' : ' – no resource'}{a.deleted_at ? ' – removed' : a.is_active ? '' : ' – inactive'}</option>)}</select></Field>
        {needsRes ? (
          <Field label="Resource (reassign)" htmlFor="e-res" hint={!b.resource_id ? 'Leave on auto to pick the best available engineer.' : undefined}><select id="e-res" className="input" value={f.resource_id} onChange={s('resource_id')}>
            {!b.resource_id && <option value="">Auto-assign best available</option>}
            {resources.data?.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}{r.is_active ? '' : ' (inactive)'}</option>)}</select></Field>
        ) : <Field label="Resource" htmlFor="e-res"><input id="e-res" className="input" disabled value="Not required" /></Field>}
        <Field label={needsRes ? 'Start date' : 'Date (optional)'} htmlFor="e-start"><input id="e-start" type="date" className="input" value={f.start_date} onChange={s('start_date')} /></Field>
        <Field label="Duration" htmlFor="e-dm">
          <select id="e-dm" className="input" value={f.duration_mode} onChange={s('duration_mode')}>
            <option value="keep">Keep current ({b.duration_days ? `${b.duration_days} working days` : 'none'})</option>
            <option value="recalculate">Recalculate from activity{act?.base_duration_days ? ` (${act.base_duration_days + (f.additional_days || 0)}d)` : ''}</option>
            <option value="duration">Override working days</option>
            <option value="end_date">Set explicit end date</option>
          </select>
        </Field>
        {f.duration_mode === 'duration' && <Field label="Working days" htmlFor="e-dd"><input id="e-dd" type="number" min={1} max={250} className="input" value={f.duration_days} onChange={s('duration_days')} /></Field>}
        {f.duration_mode === 'end_date' && <Field label="End date" htmlFor="e-ed"><input id="e-ed" type="date" className="input" value={f.end_date} onChange={s('end_date')} /></Field>}
        {act?.allow_additional_days && <Field label="Additional days" htmlFor="e-ad"><input id="e-ad" type="number" min={0} max={act.max_additional_days} className="input" value={f.additional_days} onChange={s('additional_days')} /></Field>}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Application name" htmlFor="e-an"><input id="e-an" className="input" value={f.application_name} onChange={s('application_name')} /></Field>
        <Field label="Version" htmlFor="e-av"><input id="e-av" className="input" value={f.application_version} onChange={s('application_version')} /></Field>
        <Field label="PCI DSS scope" htmlFor="e-pci"><select id="e-pci" className="input" value={f.pci ? 'yes' : 'no'} onChange={(e) => setF({ ...f, pci: e.target.value === 'yes' })}><option value="yes">Yes</option><option value="no">No</option></select></Field>
        <Field label="POC name" htmlFor="e-pn"><input id="e-pn" className="input" value={f.poc_name} onChange={s('poc_name')} /></Field>
        <Field label="POC email(s)" htmlFor="e-pe" hint="Separate several addresses with commas."><input id="e-pe" type="text" inputMode="email" className="input" value={f.poc_email} onChange={s('poc_email')} /></Field>
        <Field label="Comments" htmlFor="e-c"><input id="e-c" className="input" value={f.additional_comments} onChange={s('additional_comments')} /></Field>
        <Field label="Product" htmlFor="e-prod"><select id="e-prod" className="input" value={f.product_id} onChange={(e) => setF({ ...f, product_id: e.target.value, implementation_id: '' })}><option value="">— None —</option>{products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}{p.is_active ? '' : ' (inactive)'}</option>)}</select></Field>
        <Field label="Implementation" htmlFor="e-impl"><select id="e-impl" className="input" value={f.implementation_id} onChange={s('implementation_id')} disabled={!prod}><option value="">— None —</option>{prod?.implementations.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></Field>
      </div>
      <Field label="Reason for change *" htmlFor="e-r"><textarea id="e-r" className="input min-h-16" maxLength={2000} value={f.reason} onChange={s('reason')} /></Field>
      <div className="flex justify-end"><button className="btn-primary" disabled={busy || !f.reason.trim()}>{busy ? 'Saving…' : 'Save changes'}</button></div>
    </form>
  )
}
