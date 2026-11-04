import { useState } from 'react'
import { get, post, qs, validationMessage } from '../../api/client'
import type { Conflict } from '../../api/types'
import { AdminBookingModal } from '../../components/AdminBookingModal'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, PageHeader, Pill, Spinner, StatusBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { CONFLICT_TYPE_LABELS } from '../../lib/status'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function Conflicts() {
  const toast = useToast()
  const [status, setStatus] = useState('open')
  const [type, setType] = useState('')
  const { data, error, loading, reload } = useAsync<Conflict[]>(() => get('/api/admin/conflicts' + qs({ status, conflict_type: type })), [status, type])
  const [resolve, setResolve] = useState<Conflict | null>(null)
  const [sel, setSel] = useState<string | null>(null)
  return (
    <div>
      <PageHeader title="Scheduling Conflicts" subtitle="Bookings are never silently moved. Review each flagged booking, take any corrective action (modify, reassign, reschedule or cancel – all audited and notified), then record the resolution." />
      <details className="card mb-3 p-3 text-sm"><summary className="cursor-pointer font-medium">Resolution workflow</summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-slate-700">
          <li>Open the booking and review the conflict details, affected dates and POC.</li>
          <li>Decide: keep as-is (e.g. backup engineer), recalculate/extend, reschedule, reassign to another resource, or cancel. Use the booking's <b>Modify / Reassign</b> tab – changes are revalidated, audited and POCs of approved bookings are notified.</li>
          <li>Coordinate with the POC if dates change.</li>
          <li>Click <b>Resolve</b> and record what was done. The booking's review flag clears once all its conflicts are resolved.</li>
        </ol>
      </details>
      <div className="mb-3 flex flex-wrap gap-2">
        {['open', 'resolved', ''].map((s) => <button key={s} className={status === s ? 'btn-primary' : 'btn-secondary'} onClick={() => setStatus(s)}>{s ? s[0].toUpperCase() + s.slice(1) : 'All'}</button>)}
        <select className="input w-52" aria-label="Conflict type" value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{Object.entries(CONFLICT_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No conflicts" hint={status === 'open' ? 'Everything is consistent.' : undefined} /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Conflict</th><th className="th">Type</th><th className="th">Booking</th><th className="th">Conflicting booking</th><th className="th">Resource</th><th className="th">Dates</th><th className="th">Description</th><th className="th">Resolution</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((c) => (
              <tr key={c.id}>
                <td className="td font-mono text-xs" title={c.id}>{c.id.slice(0, 8)}<div className="text-[11px] font-sans text-slate-500">{fmtDateTime(c.created_at)}</div></td>
                <td className="td"><Pill className="bg-amber-100 text-amber-900">{CONFLICT_TYPE_LABELS[c.conflict_type]}</Pill></td>
                <td className="td"><button className="text-left font-medium text-blue-800 hover:underline" onClick={() => setSel(c.booking_id)}>{c.application_name}</button><div className="font-mono text-[11px] text-slate-500">{c.booking_id.slice(0, 8)}</div><StatusBadge status={c.booking_status} /><div className="text-[11px] text-slate-500">{fmt(c.booking_start_date)} – {fmt(c.booking_end_date)}</div></td>
                <td className="td">{c.conflicting_booking_id ? <><button className="text-left font-medium text-blue-800 hover:underline" onClick={() => setSel(c.conflicting_booking_id!)}>{c.conflicting_application_name}</button><div className="font-mono text-[11px] text-slate-500">{c.conflicting_booking_id.slice(0, 8)}</div>{c.conflicting_booking_status && <StatusBadge status={c.conflicting_booking_status} />}<div className="text-[11px] text-slate-500">{fmt(c.conflicting_start_date)} – {fmt(c.conflicting_end_date)}</div></> : '—'}</td>
                <td className="td text-xs">{c.resource_display_name}<div className="text-slate-500">{c.engineer_name}</div></td>
                <td className="td text-xs whitespace-nowrap">{fmt(c.conflict_start_date)}{c.conflict_end_date !== c.conflict_start_date && <> – {fmt(c.conflict_end_date)}</>}</td>
                <td className="td max-w-sm text-xs">{c.description}</td>
                <td className="td text-xs">{c.status === 'open' ? <Pill className="bg-red-100 text-red-800">Open</Pill> : <><Pill className="bg-emerald-100 text-emerald-800">Resolved</Pill><div className="mt-1">{c.resolution_note}</div><div className="text-slate-500">{c.resolved_by_email} · {fmtDateTime(c.resolved_at)}</div></>}</td>
                <td className="td">{c.status === 'open' && <button className="btn-secondary" onClick={() => setResolve(c)}>Resolve</button>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <ConfirmDialog open={!!resolve} onClose={() => setResolve(null)} title="Resolve conflict" confirmLabel="Mark resolved" requireReason reasonLabel="Resolution note"
        message={resolve?.description} onConfirm={async (note) => {
          try { await post(`/api/admin/conflicts/${resolve!.id}/resolve`, { resolution_note: note }); toast('success', 'Conflict resolved'); setResolve(null); reload() } catch (e) { toast('error', validationMessage(e)) }
        }} />
      {sel && <AdminBookingModal bookingId={sel} onClose={() => setSel(null)} onChanged={reload} />}
    </div>
  )
}
