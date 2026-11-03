import { useState } from 'react'
import { Plus } from 'lucide-react'
import { get, patch, post, validationMessage } from '../../api/client'
import type { ResourceAdmin } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner, StatusBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function Resources() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<ResourceAdmin[]>(() => get('/api/admin/resources'))
  const [edit, setEdit] = useState<Partial<ResourceAdmin> | null>(null)
  const [toggle, setToggle] = useState<ResourceAdmin | null>(null)
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
      <PageHeader title="Resources" subtitle="Security engineers mapped to stable anonymous identifiers. Identifiers are never reassigned; deactivate instead of deleting to preserve history."
        actions={<button className="btn-primary" onClick={() => setEdit({ engineer_name: '' })}><Plus className="h-4 w-4" />Add resource</button>} />
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No resources yet" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Identifier</th><th className="th">Engineer (admin only)</th><th className="th">Email</th><th className="th">Notes</th><th className="th">Status</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((r) => (
              <tr key={r.id}>
                <td className="td"><div className="font-semibold">{r.display_name}</div><div className="font-mono text-xs text-slate-500">{r.code}</div></td>
                <td className="td">{r.engineer_name}</td><td className="td text-xs">{r.engineer_email ?? '—'}</td><td className="td max-w-xs text-xs">{r.notes ?? ''}</td>
                <td className="td">{r.is_active ? <Pill className="bg-emerald-100 text-emerald-800">Active</Pill> : <Pill className="bg-slate-200 text-slate-700">Inactive {r.deactivated_at && `since ${fmtDateTime(r.deactivated_at)}`}</Pill>}</td>
                <td className="td whitespace-nowrap"><div className="flex gap-1">
                  <button className="btn-secondary" onClick={() => setAlloc(r)}>Allocation</button>
                  <button className="btn-secondary" onClick={() => setEdit(r)}>Edit</button>
                  <button className={r.is_active ? 'btn-secondary' : 'btn-success'} onClick={() => setToggle(r)}>{r.is_active ? 'Deactivate' : 'Activate'}</button>
                </div></td>
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
      <ConfirmDialog open={!!toggle} onClose={() => setToggle(null)} title={toggle?.is_active ? `Deactivate ${toggle?.display_name}` : `Activate ${toggle?.display_name}`}
        tone={toggle?.is_active ? 'danger' : 'success'} confirmLabel={toggle?.is_active ? 'Deactivate' : 'Activate'} requireReason={false} reasonLabel="Reason (optional)"
        message={toggle?.is_active ? 'Inactive resources are excluded from new bookings. Existing bookings are preserved and any future bookings are flagged for review.' : 'The resource will accept new bookings again.'}
        onConfirm={async (reason) => { try { const r = await patch<ResourceAdmin>(`/api/admin/resources/${toggle!.id}`, { is_active: !toggle!.is_active, reason: reason || null }); toast('success', `${r.display_name} ${r.is_active ? 'activated' : 'deactivated'}`); setToggle(null); reload() } catch (e) { toast('error', validationMessage(e)) } }} />
      {alloc && <AllocationModal r={alloc} onClose={() => setAlloc(null)} />}
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
