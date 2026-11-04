import { useState } from 'react'
import { Plus } from 'lucide-react'
import { del, get, patch, post, qs, validationMessage } from '../../api/client'
import type { Leave, ResourceAdmin } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { fmt } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

const TYPES = ['Annual leave', 'Sick leave', 'Training', 'Public duty', 'Other']

export default function LeavePage() {
  const toast = useToast()
  const [resource, setResource] = useState('')
  const [showCancelled, setShowCancelled] = useState(false)
  const resources = useAsync<ResourceAdmin[]>(() => get('/api/admin/resources'))
  const { data, error, loading, reload } = useAsync<Leave[]>(() => get('/api/admin/leaves' + qs({ resource_id: resource, include_cancelled: showCancelled })), [resource, showCancelled])
  const [edit, setEdit] = useState<Partial<Leave> | null>(null)
  const [cancel, setCancel] = useState<Leave | null>(null)
  const flagged = (r: any) => r.flagged_bookings?.length ? toast('info', `${r.flagged_bookings.length} booking(s) flagged for review – see Conflicts`) : null
  const save = async () => {
    try {
      const body: any = { start_date: edit!.start_date, end_date: edit!.end_date, leave_type: edit!.leave_type || null, reason: edit!.reason || null }
      const r = edit!.id ? await patch(`/api/admin/leaves/${edit!.id}`, body) : await post('/api/admin/leaves', { ...body, resource_id: edit!.resource_id })
      toast('success', 'Leave saved'); flagged(r); setEdit(null); reload()
    } catch (e) { toast('error', validationMessage(e)) }
  }
  return (
    <div>
      <PageHeader title="Individual Leave" subtitle="Leave makes only the mapped resource unavailable. Approved bookings affected by leave are flagged for review – never moved automatically."
        actions={<button className="btn-primary" onClick={() => setEdit({ resource_id: resource || resources.data?.[0]?.id, leave_type: 'Annual leave' })}><Plus className="h-4 w-4" />Add leave</button>} />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <select className="input w-72" aria-label="Filter by resource" value={resource} onChange={(e) => setResource(e.target.value)}><option value="">All resources</option>{resources.data?.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}</option>)}</select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} />Show cancelled</label>
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No leave recorded" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Resource</th><th className="th">Engineer</th><th className="th">From</th><th className="th">To</th><th className="th">Type</th><th className="th">Reason</th><th className="th">Status</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((l) => (
              <tr key={l.id} className={l.status === 'cancelled' ? 'opacity-60' : ''}>
                <td className="td font-medium">{l.resource_display_name}</td><td className="td">{l.engineer_name}</td><td className="td">{fmt(l.start_date)}</td><td className="td">{fmt(l.end_date)}</td>
                <td className="td">{l.leave_type ?? '—'}</td><td className="td max-w-xs text-xs">{l.reason}</td><td className="td"><Pill>{l.status}</Pill></td>
                <td className="td whitespace-nowrap">{l.status === 'active' && <div className="flex gap-1"><button className="btn-secondary" onClick={() => setEdit(l)}>Edit</button><button className="btn-secondary" onClick={() => setCancel(l)}>Cancel</button></div>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? 'Edit leave' : 'Add leave'} size="sm"
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" disabled={!edit?.resource_id || !edit?.start_date || !edit?.end_date} onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          <Field label="Resource *" htmlFor="l-r"><select id="l-r" className="input" disabled={!!edit.id} value={edit.resource_id} onChange={(e) => setEdit({ ...edit, resource_id: e.target.value })}>{resources.data?.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}</option>)}</select></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Start date *" htmlFor="l-s"><input id="l-s" type="date" className="input" value={edit.start_date ?? ''} onChange={(e) => setEdit({ ...edit, start_date: e.target.value, end_date: edit.end_date && edit.end_date >= e.target.value ? edit.end_date : e.target.value })} /></Field>
            <Field label="End date *" htmlFor="l-e"><input id="l-e" type="date" className="input" min={edit.start_date} value={edit.end_date ?? ''} onChange={(e) => setEdit({ ...edit, end_date: e.target.value })} /></Field>
          </div>
          <Field label="Leave type" htmlFor="l-t"><select id="l-t" className="input" value={edit.leave_type ?? ''} onChange={(e) => setEdit({ ...edit, leave_type: e.target.value })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
          <Field label="Reason / description" htmlFor="l-d" hint="Visible to admins only."><textarea id="l-d" className="input" value={edit.reason ?? ''} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} /></Field>
          <p className="text-xs text-slate-500">Full-day leave. Pending and approved bookings on these dates will be flagged for review.</p>
        </div>}
      </Modal>
      <ConfirmDialog open={!!cancel} onClose={() => setCancel(null)} title="Cancel leave" tone="danger" confirmLabel="Cancel leave"
        message={`Cancel leave for ${cancel?.engineer_name} (${fmt(cancel?.start_date)} – ${fmt(cancel?.end_date)})? Bookings spanning these dates will be flagged for schedule review.`}
        onConfirm={async () => { try { const r = await del(`/api/admin/leaves/${cancel!.id}`); toast('success', 'Leave cancelled'); flagged(r); setCancel(null); reload() } catch (e) { toast('error', validationMessage(e)) } }} />
    </div>
  )
}
