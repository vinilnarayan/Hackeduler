import { useState } from 'react'
import { Plus } from 'lucide-react'
import { ApiError, del, get, patch, post, validationMessage } from '../../api/client'
import type { ResourceAdmin } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner, StatusBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function Resources() {
  const toast = useToast()
  const [showDeleted, setShowDeleted] = useState(false)
  const { data, error, loading, reload } = useAsync<ResourceAdmin[]>(() => get(`/api/admin/resources${showDeleted ? '?include_deleted=true' : ''}`), [showDeleted])
  const [remove, setRemove] = useState<ResourceAdmin | null>(null)
  const [inUse, setInUse] = useState<{ r: ResourceAdmin; bookings: any[] } | null>(null)
  const restore = async (r: ResourceAdmin) => { try { await post(`/api/admin/resources/${r.id}/restore`); toast('success', `${r.display_name} restored (inactive). Activate it when ready.`); reload() } catch (e) { toast('error', validationMessage(e)) } }
  const [edit, setEdit] = useState<Partial<ResourceAdmin> | null>(null)
  const [toggle, setToggle] = useState<ResourceAdmin | null>(null)
  const [cancelSched, setCancelSched] = useState<ResourceAdmin | null>(null)
  const [alloc, setAlloc] = useState<ResourceAdmin | null>(null)
  const save = async () => {
    try {
      const body = { engineer_name: edit!.engineer_name, engineer_email: edit!.engineer_email || null, notes: edit!.notes || null }
      if (edit!.id) await patch(`/api/admin/resources/${edit!.id}`, body); else await post('/api/admin/resources', body)
      toast('success', 'Resource saved'); setEdit(null); reload()
    } catch (e) { toast('error', validationMessage(e)) }
  }
  return (
    <div>
      <PageHeader title="Resources" subtitle="Security engineers mapped to stable anonymous identifiers. Identifiers are never reassigned. Deleting a resource that has booking history archives it, so past bookings stay intact."
        actions={<>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />Show deleted</label>
          <button className="btn-primary" onClick={() => setEdit({ engineer_name: '' })}><Plus className="h-4 w-4" />Add resource</button>
        </>} />
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No resources yet" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Identifier</th><th className="th">Engineer (admin only)</th><th className="th">Email</th><th className="th">Notes</th><th className="th">Status</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((r) => (
              <tr key={r.id} className={r.deleted_at ? 'bg-slate-50 opacity-70' : ''}>
                <td className="td"><div className="font-semibold">{r.display_name}</div><div className="font-mono text-xs text-slate-500">{r.code}</div></td>
                <td className="td">{r.engineer_name}</td><td className="td text-xs">{r.engineer_email ?? '—'}</td><td className="td max-w-xs text-xs">{r.notes ?? ''}</td>
                <td className="td">
                  {r.deleted_at ? <Pill className="bg-red-100 text-red-800">Deleted {fmtDateTime(r.deleted_at)}</Pill>
                    : !r.is_active ? <Pill className="bg-slate-200 text-slate-700">Inactive since {r.inactive_from ? fmt(r.inactive_from) : fmtDateTime(r.deactivated_at)}</Pill>
                    : r.inactive_from ? <Pill className="bg-amber-100 text-amber-800">Active · inactive from {fmt(r.inactive_from)}</Pill>
                    : <Pill className="bg-emerald-100 text-emerald-800">Active</Pill>}
                  {r.inactive_reason && <div className="mt-1 max-w-48 text-xs text-slate-500">{r.inactive_reason}</div>}
                </td>
                <td className="td whitespace-nowrap">{r.deleted_at ? <button className="btn-secondary" onClick={() => restore(r)}>Restore</button> : <div className="flex gap-1">
                  <button className="btn-secondary" onClick={() => setAlloc(r)}>Allocation</button>
                  <button className="btn-secondary" onClick={() => setEdit(r)}>Edit</button>
                  {r.is_active && r.inactive_from
                    ? <button className="btn-secondary" onClick={() => setCancelSched(r)}>Cancel deactivation</button>
                    : <button className={r.is_active ? 'btn-secondary' : 'btn-success'} onClick={() => setToggle(r)}>{r.is_active ? 'Deactivate' : 'Activate'}</button>}
                  <button className="btn-ghost px-2 text-red-700" onClick={() => setRemove(r)}>Delete</button>
                </div>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? `Edit ${edit.display_name}` : 'Add resource'} size="sm"
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" disabled={!edit?.engineer_name?.trim()} onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          {!edit.id && <p className="text-xs text-slate-500">The next anonymous identifier (Resource NN) is assigned automatically.</p>}
          <Field label="Engineer name *" htmlFor="r-n"><input id="r-n" className="input" value={edit.engineer_name ?? ''} onChange={(e) => setEdit({ ...edit, engineer_name: e.target.value })} /></Field>
          <Field label="Engineer email" htmlFor="r-e"><input id="r-e" type="email" className="input" value={edit.engineer_email ?? ''} onChange={(e) => setEdit({ ...edit, engineer_email: e.target.value })} /></Field>
          <Field label="Notes" htmlFor="r-no"><textarea id="r-no" className="input" value={edit.notes ?? ''} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></Field>
        </div>}
      </Modal>
      {toggle?.is_active && <DeactivateDialog r={toggle} onClose={() => setToggle(null)} onDone={() => { setToggle(null); reload() }} />}
      <ConfirmDialog open={!!toggle && !toggle.is_active} onClose={() => setToggle(null)} title={`Activate ${toggle?.display_name}`}
        tone="success" confirmLabel="Activate" message="The resource will accept new bookings again."
        onConfirm={async () => { try { const r = await patch<ResourceAdmin>(`/api/admin/resources/${toggle!.id}`, { is_active: true }); toast('success', `${r.display_name} activated`); setToggle(null); reload() } catch (e) { toast('error', validationMessage(e)) } }} />
      <ConfirmDialog open={!!cancelSched} onClose={() => setCancelSched(null)} title={`Cancel scheduled deactivation`} tone="primary" confirmLabel="Keep resource active"
        message={<>{cancelSched?.display_name} ({cancelSched?.engineer_name}) is scheduled to become inactive on <b>{fmt(cancelSched?.inactive_from)}</b>. Cancel this and keep the resource available? Conflicts already raised stay open for you to resolve.</>}
        onConfirm={async () => { try { await patch(`/api/admin/resources/${cancelSched!.id}`, { inactive_from: null }); toast('success', 'Scheduled deactivation cancelled'); setCancelSched(null); reload() } catch (e) { toast('error', validationMessage(e)) } }} />
      {alloc && <AllocationModal r={alloc} onClose={() => setAlloc(null)} />}
      <ConfirmDialog open={!!remove} onClose={() => setRemove(null)} title={`Delete ${remove?.display_name} – ${remove?.engineer_name}`} tone="danger" confirmLabel="Delete resource"
        message={<div className="space-y-2"><p>The resource disappears from the calendar, booking screens and resource lists.</p>
          <p className="text-xs text-slate-600">If it was ever booked, its past bookings keep showing <b>{remove?.display_name}</b> (the record is archived, not erased, and the identifier is never reused). Its leave records are removed. Resources with pending or approved bookings can't be deleted until those are reassigned or cancelled.</p></div>}
        onConfirm={async () => {
          const r = remove!
          try { const res = await del<any>(`/api/admin/resources/${r.id}`); toast('success', `${r.display_name} deleted${res.mode === 'archived' ? ' (archived with its booking history)' : ''}`); setRemove(null); reload() }
          catch (e) { setRemove(null); if (e instanceof ApiError && e.code === 'resource_in_use') setInUse({ r, bookings: e.details?.bookings ?? [] }); else toast('error', validationMessage(e)) }
        }} />
      <Modal open={!!inUse} onClose={() => setInUse(null)} size="md" title={`${inUse?.r.display_name} still has active bookings`}>
        <p className="mb-2 text-sm">Reassign these bookings to another resource (Bookings → open booking → Modify / Reassign) or cancel them, then delete the resource.</p>
        <ul className="divide-y divide-slate-100 text-sm">{inUse?.bookings.map((b) => <li key={b.id} className="flex items-center gap-2 py-1.5"><span className="flex-1">{b.application_name}</span><span className="text-xs">{fmt(b.start_date)} – {fmt(b.end_date)}</span><StatusBadge status={b.status} /></li>)}</ul>
      </Modal>
    </div>
  )
}

function AllocationModal({ r, onClose }: { r: ResourceAdmin; onClose: () => void }) {
  const { data, loading } = useAsync<any>(() => get(`/api/admin/resources/${r.id}/allocation`), [r.id])
  return (
    <Modal open onClose={onClose} size="lg" title={`${r.display_name} – ${r.engineer_name}: bookings & leave`}>
      {loading || !data ? <Spinner /> : (
        <div className="space-y-4 text-sm">
          <div><div className="label">Bookings (−90 / +180 days)</div>{data.bookings.length === 0 ? <p className="text-slate-500">None</p> : (
            <ul className="divide-y divide-slate-100">{data.bookings.map((b: any) => <li key={b.id} className="flex flex-wrap items-center gap-2 py-1.5"><span className="flex-1">{b.application_name} <span className="text-xs text-slate-500">({b.activity_name})</span></span><span className="text-xs">{fmt(b.start_date)} – {fmt(b.end_date)}</span><StatusBadge status={b.status} /></li>)}</ul>)}</div>
          <div><div className="label">Leave</div>{data.leaves.length === 0 ? <p className="text-slate-500">None</p> : (
            <ul className="divide-y divide-slate-100">{data.leaves.map((l: any) => <li key={l.id} className="flex gap-2 py-1.5"><span className="flex-1">{l.leave_type ?? 'Leave'}{l.reason ? ` – ${l.reason}` : ''}</span><span className="text-xs">{fmt(l.start_date)} – {fmt(l.end_date)}</span><Pill>{l.status}</Pill></li>)}</ul>)}</div>
        </div>
      )}
    </Modal>
  )
}

function DeactivateDialog({ r, onClose, onDone }: { r: ResourceAdmin; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const settings = useAsync<any>(() => get('/api/settings/public'))
  const today = settings.data?.today as string | undefined
  const [mode, setMode] = useState<'now' | 'date'>('date')
  const [from, setFrom] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const valid = mode === 'now' || (!!from && (!today || from >= today))
  const submit = async () => {
    setBusy(true)
    try {
      const body = mode === 'now' ? { is_active: false, reason: reason || null } : { inactive_from: from, reason: reason || null }
      const res = await patch<ResourceAdmin>(`/api/admin/resources/${r.id}`, body)
      toast('success', res.is_active ? `${res.display_name} will be inactive from ${fmt(res.inactive_from)}` : `${res.display_name} deactivated`)
      onDone()
    } catch (e) { toast('error', validationMessage(e)) } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} size="sm" title={`Deactivate ${r.display_name} – ${r.engineer_name}`}
      footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-danger" disabled={!valid || busy} onClick={submit}>{busy ? 'Saving…' : mode === 'now' ? 'Deactivate now' : 'Schedule deactivation'}</button></>}>
      <div className="space-y-3 text-sm">
        <fieldset className="space-y-2"><legend className="label">When</legend>
          <label className={`flex cursor-pointer gap-2 rounded-md border p-2 ${mode === 'date' ? 'border-blue-600 bg-blue-50' : 'border-slate-200'}`}>
            <input type="radio" name="deact" className="mt-0.5" checked={mode === 'date'} onChange={() => setMode('date')} />
            <span><span className="font-medium">From a specific date</span><span className="block text-xs text-slate-600">Bookable until the day before. From this date it shows as inactive and can't be booked.</span></span>
          </label>
          <label className={`flex cursor-pointer gap-2 rounded-md border p-2 ${mode === 'now' ? 'border-blue-600 bg-blue-50' : 'border-slate-200'}`}>
            <input type="radio" name="deact" className="mt-0.5" checked={mode === 'now'} onChange={() => setMode('now')} />
            <span><span className="font-medium">Immediately (today)</span><span className="block text-xs text-slate-600">Excluded from all new bookings from today.</span></span>
          </label>
        </fieldset>
        {mode === 'date' && <Field label="Inactive from *" htmlFor="d-from" hint="First day the engineer is unavailable."><input id="d-from" type="date" className="input w-48" min={today} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>}
        <Field label="Reason" htmlFor="d-reason" hint="Admin-only; recorded in the audit log."><textarea id="d-reason" className="input min-h-16" maxLength={2000} placeholder="e.g. Moving to another team" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <p className="rounded bg-amber-50 p-2 text-xs text-amber-900">Existing pending or approved bookings that run on or after this date are <b>not changed</b>. They are flagged under Conflicts for reassignment, and POCs of approved bookings are notified. History is preserved.</p>
      </div>
    </Modal>
  )
}
