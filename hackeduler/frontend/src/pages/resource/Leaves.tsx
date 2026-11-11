import { useState } from 'react'
import { Plus } from 'lucide-react'
import { del, get, post, validationMessage } from '../../api/client'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Spinner } from '../../components/ui'
import { fmt, iso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

interface MyLeave { id: string; start_date: string; end_date: string; leave_type: string | null; reason: string | null }
const TYPES = ['Annual leave', 'Sick leave', 'Training', 'Public duty', 'Other']

export default function ResourceLeaves() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<MyLeave[]>(() => get('/api/resource/leaves'))
  const [edit, setEdit] = useState<Partial<MyLeave> | null>(null)
  const [cancel, setCancel] = useState<MyLeave | null>(null)
  const today = iso(new Date())
  const save = async () => {
    try {
      const r = await post<any>('/api/resource/leaves', { start_date: edit!.start_date, end_date: edit!.end_date, leave_type: edit!.leave_type || null, reason: edit!.reason || null })
      toast('success', 'Leave added'); if (r.flagged_bookings) toast('info', `${r.flagged_bookings} booking(s) overlap this leave and were flagged for the administrators to review`)
      setEdit(null); reload()
    } catch (e) { toast('error', validationMessage(e)) }
  }
  return (
    <div>
      <PageHeader title="My leave" subtitle="Add your upcoming leave. Administrators are told about any booking that overlaps it; nothing is rescheduled automatically."
        actions={<button className="btn-primary" onClick={() => setEdit({ leave_type: 'Annual leave' })}><Plus className="h-4 w-4" />Add leave</button>} />
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No upcoming leave" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">From</th><th className="th">To</th><th className="th">Type</th><th className="th">Reason</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((l) => (
              <tr key={l.id}><td className="td">{fmt(l.start_date)}</td><td className="td">{fmt(l.end_date)}</td><td className="td">{l.leave_type ?? '—'}</td><td className="td max-w-xs text-xs">{l.reason}</td>
                <td className="td"><button className="btn-secondary" onClick={() => setCancel(l)}>Cancel</button></td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title="Add leave" size="sm"
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Close</button><button className="btn-primary" disabled={!edit?.start_date || !edit?.end_date} onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Start date *" htmlFor="rl-s"><input id="rl-s" type="date" className="input" min={today} value={edit.start_date ?? ''} onChange={(e) => setEdit({ ...edit, start_date: e.target.value, end_date: edit.end_date && edit.end_date >= e.target.value ? edit.end_date : e.target.value })} /></Field>
            <Field label="End date *" htmlFor="rl-e"><input id="rl-e" type="date" className="input" min={edit.start_date ?? today} value={edit.end_date ?? ''} onChange={(e) => setEdit({ ...edit, end_date: e.target.value })} /></Field>
          </div>
          <Field label="Leave type" htmlFor="rl-t"><select id="rl-t" className="input" value={edit.leave_type ?? ''} onChange={(e) => setEdit({ ...edit, leave_type: e.target.value })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
          <Field label="Reason / description" htmlFor="rl-d"><textarea id="rl-d" className="input" value={edit.reason ?? ''} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} /></Field>
        </div>}
      </Modal>
      <ConfirmDialog open={!!cancel} onClose={() => setCancel(null)} title="Cancel leave" tone="danger" confirmLabel="Cancel leave"
        message={`Cancel your leave ${fmt(cancel?.start_date)} – ${fmt(cancel?.end_date)}?`}
        onConfirm={async () => { try { await del(`/api/resource/leaves/${cancel!.id}`); toast('success', 'Leave cancelled'); setCancel(null); reload() } catch (e) { toast('error', validationMessage(e)) } }} />
    </div>
  )
}
