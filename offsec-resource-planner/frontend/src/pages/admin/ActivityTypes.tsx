import { useState } from 'react'
import { Plus } from 'lucide-react'
import { get, patch, post, validationMessage } from '../../api/client'
import type { ActivityType } from '../../api/types'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function ActivityTypes() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<ActivityType[]>(() => get('/api/admin/activity-types'))
  const [edit, setEdit] = useState<Partial<ActivityType> | null>(null)
  const valid = edit && edit.name?.trim() && Number.isInteger(edit.base_duration_days) && (edit.base_duration_days ?? 0) > 0 &&
    (!edit.allow_additional_days || (Number.isInteger(edit.max_additional_days) && (edit.max_additional_days ?? 0) > 0))
  const save = async () => {
    const body = { name: edit!.name, description: edit!.description || null, base_duration_days: edit!.base_duration_days, allow_additional_days: !!edit!.allow_additional_days,
      max_additional_days: edit!.allow_additional_days ? edit!.max_additional_days : 0, sort_order: edit!.sort_order ?? 0 }
    try { if (edit!.id) await patch(`/api/admin/activity-types/${edit!.id}`, body); else await post('/api/admin/activity-types', body); toast('success', 'Activity type saved'); setEdit(null); reload() }
    catch (e) { toast('error', validationMessage(e)) }
  }
  const toggle = async (a: ActivityType) => { try { await patch(`/api/admin/activity-types/${a.id}`, { is_active: !a.is_active }); toast('success', `${a.name} ${a.is_active ? 'deactivated' : 'activated'}`); reload() } catch (e) { toast('error', validationMessage(e)) } }
  return (
    <div>
      <PageHeader title="Activity Types" subtitle="Standard durations in working days. Changes apply to new bookings only – each booking keeps a snapshot of its duration."
        actions={<button className="btn-primary" onClick={() => setEdit({ name: '', base_duration_days: 8, allow_additional_days: false, max_additional_days: 0 })}><Plus className="h-4 w-4" />Add activity type</button>} />
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No activity types" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Activity type</th><th className="th">Duration</th><th className="th">Additional days</th><th className="th">Status</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((a) => (
              <tr key={a.id} className={a.is_active ? '' : 'opacity-60'}>
                <td className="td"><div className="font-medium">{a.name}</div>{a.description && <div className="text-xs text-slate-500">{a.description}</div>}</td>
                <td className="td tabular-nums">{a.base_duration_days} working days</td>
                <td className="td">{a.allow_additional_days ? `Up to +${a.max_additional_days}` : '—'}</td>
                <td className="td">{a.is_active ? <Pill className="bg-emerald-100 text-emerald-800">Active</Pill> : <Pill>Inactive</Pill>}</td>
                <td className="td whitespace-nowrap"><div className="flex gap-1"><button className="btn-secondary" onClick={() => setEdit(a)}>Edit</button><button className="btn-secondary" onClick={() => toggle(a)}>{a.is_active ? 'Deactivate' : 'Activate'}</button></div></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? 'Edit activity type' : 'Add activity type'} size="sm"
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" disabled={!valid} onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          <Field label="Name *" htmlFor="a-n"><input id="a-n" className="input" value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Description / scope" htmlFor="a-d"><input id="a-d" className="input" value={edit.description ?? ''} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
          <Field label="Duration (working days) *" htmlFor="a-du" hint="Positive whole number." error={edit.base_duration_days !== undefined && !(Number.isInteger(edit.base_duration_days) && edit.base_duration_days > 0) ? 'Must be a positive integer' : undefined}>
            <input id="a-du" type="number" min={1} step={1} className="input" value={edit.base_duration_days ?? ''} onChange={(e) => setEdit({ ...edit, base_duration_days: Number(e.target.value) })} />
          </Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.allow_additional_days} onChange={(e) => setEdit({ ...edit, allow_additional_days: e.target.checked, max_additional_days: e.target.checked ? edit.max_additional_days || 1 : 0 })} />Allow requesters to add extra working days</label>
          {edit.allow_additional_days && <Field label="Maximum additional days" htmlFor="a-m"><input id="a-m" type="number" min={1} step={1} className="input" value={edit.max_additional_days ?? 1} onChange={(e) => setEdit({ ...edit, max_additional_days: Number(e.target.value) })} /></Field>}
          <Field label="Sort order" htmlFor="a-s"><input id="a-s" type="number" className="input" value={edit.sort_order ?? 0} onChange={(e) => setEdit({ ...edit, sort_order: Number(e.target.value) })} /></Field>
        </div>}
      </Modal>
    </div>
  )
}
