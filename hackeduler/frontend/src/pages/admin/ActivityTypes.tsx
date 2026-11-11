import { useState } from 'react'
import { Plus } from 'lucide-react'
import { del, get, patch, post, validationMessage } from '../../api/client'
import type { ActivityType } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function ActivityTypes() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<ActivityType[]>(() => get('/api/admin/activity-types'))
  const [edit, setEdit] = useState<Partial<ActivityType> | null>(null)
  const [remove, setRemove] = useState<ActivityType | null>(null)
  const durOk = (v: number | null | undefined) => v == null || (Number.isInteger(v) && v > 0)
  const valid = edit && edit.name?.trim() && durOk(edit.base_duration_days) && (!edit.requires_resource || (edit.base_duration_days ?? 0) > 0) &&
    (!edit.allow_additional_days || (Number.isInteger(edit.max_additional_days) && (edit.max_additional_days ?? 0) > 0))
  const save = async () => {
    const body = { name: edit!.name, description: edit!.description || null, base_duration_days: edit!.base_duration_days || null,
      requires_resource: edit!.requires_resource !== false, allow_additional_days: !!edit!.allow_additional_days && !!edit!.base_duration_days,
      max_additional_days: edit!.allow_additional_days ? edit!.max_additional_days : 0, sort_order: edit!.sort_order ?? 0,
      visible_to_requesters: edit!.visible_to_requesters !== false,
      initiation_email_enabled: edit!.initiation_email_enabled !== false,
      initiation_days_before: edit!.initiation_days_before == null || (edit!.initiation_days_before as unknown) === '' ? null : Number(edit!.initiation_days_before),
      initiation_details: edit!.initiation_details?.trim() ? edit!.initiation_details : null }
    try { if (edit!.id) await patch(`/api/admin/activity-types/${edit!.id}`, body); else await post('/api/admin/activity-types', body); toast('success', 'Activity type saved'); setEdit(null); reload() }
    catch (e) { toast('error', validationMessage(e)) }
  }
  const toggle = async (a: ActivityType) => { try { await patch(`/api/admin/activity-types/${a.id}`, { is_active: !a.is_active }); toast('success', `${a.name} ${a.is_active ? 'deactivated' : 'activated'}`); reload() } catch (e) { toast('error', validationMessage(e)) } }
  return (
    <div>
      <PageHeader title="Activity Types" subtitle="Standard durations in working days. Changes apply to new bookings only – each booking keeps a snapshot of its duration."
        actions={<button className="btn-primary" onClick={() => setEdit({ name: '', base_duration_days: 8, requires_resource: true, allow_additional_days: false, max_additional_days: 0, visible_to_requesters: true, initiation_email_enabled: true, initiation_days_before: null, initiation_details: null })}><Plus className="h-4 w-4" />Add activity type</button>} />
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No activity types" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Activity type</th><th className="th">Duration</th><th className="th">Resource</th><th className="th">Additional days</th><th className="th">Status</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((a) => (
              <tr key={a.id} className={a.is_active ? '' : 'opacity-60'}>
                <td className="td"><div className="font-medium">{a.name}</div>{a.description && <div className="text-xs text-slate-500">{a.description}</div>}</td>
                <td className="td tabular-nums">{a.base_duration_days ? `${a.base_duration_days} working days` : <span className="text-slate-400">Not set</span>}</td>
                <td className="td">{a.requires_resource ? <Pill className="bg-blue-100 text-blue-800">Security resource</Pill> : <Pill>No resource</Pill>}</td>
                <td className="td">{a.allow_additional_days ? `Up to +${a.max_additional_days}` : '—'}</td>
                <td className="td"><div className="flex flex-wrap gap-1">{a.is_active ? <Pill className="bg-emerald-100 text-emerald-800">Active</Pill> : <Pill>Inactive</Pill>}{!a.visible_to_requesters && <Pill className="bg-amber-100 text-amber-800">Hidden from requesters</Pill>}</div></td>
                <td className="td whitespace-nowrap"><div className="flex gap-1"><button className="btn-secondary" onClick={() => setEdit(a)}>Edit</button><button className="btn-secondary" onClick={() => toggle(a)}>{a.is_active ? 'Deactivate' : 'Activate'}</button><button className="btn-secondary text-red-700" onClick={() => setRemove(a)}>Remove</button></div></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <ConfirmDialog open={!!remove} onClose={() => setRemove(null)} title={`Remove ${remove?.name}`} tone="danger" confirmLabel="Remove activity type"
        message={<div className="space-y-2"><p>This activity type disappears from every list and can no longer be booked.</p>
          <p className="text-xs text-slate-600">Existing bookings are not changed. If the type was ever used, it is archived (not erased) so past bookings, reports and the audit trail keep showing <b>{remove?.name}</b>. To only stop new bookings temporarily, use Deactivate instead.</p></div>}
        onConfirm={async () => {
          const a = remove!
          try { const res = await del<{ mode: string }>(`/api/admin/activity-types/${a.id}`); toast('success', `${a.name} removed${res.mode === 'archived' ? ' (archived with its booking history)' : ''}`); setRemove(null); reload() }
          catch (e) { setRemove(null); toast('error', validationMessage(e)) }
        }} />
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? 'Edit activity type' : 'Add activity type'} size="sm"
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" disabled={!valid} onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          <Field label="Name *" htmlFor="a-n"><input id="a-n" className="input" value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Description / scope" htmlFor="a-d"><input id="a-d" className="input" value={edit.description ?? ''} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
          <label className="flex items-start gap-2 rounded-md border border-slate-200 p-2 text-sm"><input type="checkbox" className="mt-0.5" checked={edit.requires_resource !== false} onChange={(e) => setEdit({ ...edit, requires_resource: e.target.checked })} />
            <span><span className="font-medium">Requires a security resource</span><span className="block text-xs text-slate-500">Turn off for activities such as automated scans (e.g. XBOW): no engineer is reserved, and the duration and booking date become optional.</span></span></label>
          <Field label={edit.requires_resource !== false ? 'Duration (working days) *' : 'Duration (working days, optional)'} htmlFor="a-du" hint="Positive whole number."
            error={!durOk(edit.base_duration_days) ? 'Must be a positive integer' : edit.requires_resource !== false && !edit.base_duration_days ? 'Required for activities that need a security resource' : undefined}>
            <input id="a-du" type="number" min={1} step={1} className="input" value={edit.base_duration_days ?? ''} onChange={(e) => setEdit({ ...edit, base_duration_days: e.target.value === '' ? null : Number(e.target.value) })} />
          </Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.allow_additional_days} onChange={(e) => setEdit({ ...edit, allow_additional_days: e.target.checked, max_additional_days: e.target.checked ? edit.max_additional_days || 1 : 0 })} />Allow requesters to add extra working days</label>
          {edit.allow_additional_days && <Field label="Maximum additional days" htmlFor="a-m"><input id="a-m" type="number" min={1} step={1} className="input" value={edit.max_additional_days ?? 1} onChange={(e) => setEdit({ ...edit, max_additional_days: Number(e.target.value) })} /></Field>}
          <label className="flex items-start gap-2 rounded-md border border-slate-200 p-2 text-sm"><input type="checkbox" className="mt-0.5" checked={edit.visible_to_requesters !== false} onChange={(e) => setEdit({ ...edit, visible_to_requesters: e.target.checked })} />
            <span><span className="font-medium">Visible to requesters</span><span className="block text-xs text-slate-500">Turn off to keep this type admin-only: requesters never see it or can book it, but admins can still book it (e.g. via Manual Allocation).</span></span></label>
          <div className="space-y-2 rounded-md border border-slate-200 p-2">
            <label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" checked={edit.initiation_email_enabled !== false} onChange={(e) => setEdit({ ...edit, initiation_email_enabled: e.target.checked })} />Send the Activity initiation email for this type</label>
            {edit.initiation_email_enabled !== false && <>
              <Field label="Days before start (this type)" htmlFor="a-id" hint="Leave empty to use the number of days from Settings."><input id="a-id" type="number" min={0} max={365} className="input w-40" value={edit.initiation_days_before ?? ''} onChange={(e) => setEdit({ ...edit, initiation_days_before: e.target.value === '' ? null : Number(e.target.value) })} /></Field>
              <Field label="Details to ask the POC for" htmlFor="a-idt" hint="Used for {{Required Details}} in the email. Leave empty to use the built-in checklist for this kind of activity (shown below).">
                <textarea id="a-idt" className="input min-h-28 font-mono text-xs" value={edit.initiation_details ?? ''} placeholder={edit.initiation_details_default ?? 'Built-in checklist for this kind of activity'} onChange={(e) => setEdit({ ...edit, initiation_details: e.target.value })} />
              </Field>
              {edit.initiation_details_default && <button type="button" className="btn-ghost text-xs" onClick={() => setEdit({ ...edit, initiation_details: edit.initiation_details_default })}>Start from the built-in checklist</button>}
            </>}
          </div>
          <Field label="Sort order" htmlFor="a-s"><input id="a-s" type="number" className="input" value={edit.sort_order ?? 0} onChange={(e) => setEdit({ ...edit, sort_order: Number(e.target.value) })} /></Field>
        </div>}
      </Modal>
    </div>
  )
}
