import { useState } from 'react'
import { get, post } from '../../api/client'
import { AdminBookingModal } from '../../components/AdminBookingModal'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useForceFlow } from '../../components/useForceFlow'
import { Empty, ErrorState, PageHeader, Pill, Spinner, StatusBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function ChangeRequests() {
  const toast = useToast()
  const [status, setStatus] = useState('pending')
  const { data, error, loading, reload } = useAsync<any[]>(() => get(`/api/admin/change-requests?status=${status}`), [status])
  const [act, setAct] = useState<{ cr: any; approve: boolean } | null>(null)
  const [sel, setSel] = useState<string | null>(null)
  const force = useForceFlow()
  return (
    <div>
      <PageHeader title="Change Requests" subtitle="Requester cancellation and reschedule requests. Reschedules are revalidated before they are applied." />
      <div className="mb-3 flex gap-1">{['pending', 'approved', 'rejected', ''].map((s) => <button key={s} className={status === s ? 'btn-primary' : 'btn-secondary'} onClick={() => setStatus(s)}>{s ? s[0].toUpperCase() + s.slice(1) : 'All'}</button>)}</div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No change requests" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Type</th><th className="th">Booking</th><th className="th">Current schedule</th><th className="th">Proposed</th><th className="th">Reason</th><th className="th">Requested</th><th className="th">Status</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((cr) => (
              <tr key={cr.id}>
                <td className="td"><Pill className={cr.request_type === 'cancel' ? 'bg-red-100 text-red-800' : 'bg-blue-100 text-blue-800'}>{cr.request_type}</Pill></td>
                <td className="td"><button className="text-left font-medium text-blue-800 hover:underline" onClick={() => setSel(cr.booking_id)}>{cr.booking.application_name}</button><div className="text-xs text-slate-500">{cr.booking.requester_name}</div><StatusBadge status={cr.booking.status} /></td>
                <td className="td text-xs">{cr.booking.resource_display_name} ({cr.booking.engineer_name})<br />{fmt(cr.booking.start_date)} – {fmt(cr.booking.end_date)}</td>
                <td className="td text-xs">{cr.proposed_start_date ? `Start ${fmt(cr.proposed_start_date)}` : '—'}</td>
                <td className="td max-w-xs text-xs">{cr.reason}{cr.decision_note && <div className="mt-1 text-slate-500">Decision: {cr.decision_note}</div>}</td>
                <td className="td text-xs">{fmtDateTime(cr.created_at)}</td>
                <td className="td text-xs">{cr.status}</td>
                <td className="td whitespace-nowrap">{cr.status === 'pending' && <div className="flex gap-1"><button className="btn-success" onClick={() => setAct({ cr, approve: true })}>Approve</button><button className="btn-danger" onClick={() => setAct({ cr, approve: false })}>Decline</button></div>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <ConfirmDialog open={!!act} onClose={() => setAct(null)} title={act?.approve ? `Approve ${act?.cr.request_type} request` : 'Decline request'}
        tone={act?.approve ? 'success' : 'danger'} confirmLabel={act?.approve ? 'Approve' : 'Decline'} requireReason={!act?.approve} reasonLabel={act?.approve ? 'Admin note (optional)' : 'Reason (sent to requester)'}
        message={act?.approve ? (act.cr.request_type === 'cancel' ? 'The booking will be cancelled and its reservation released.' : `The booking will be moved to start ${fmt(act.cr.proposed_start_date)} after server-side revalidation. The old reservation is released only if the new one succeeds.`) : 'The booking stays unchanged.'}
        onConfirm={async (note) => {
          const a = act!; setAct(null)
          await force.run((f) => post(`/api/admin/change-requests/${a.cr.id}/decide`, { approve: a.approve, note: note || null, ...(f ? { force: f } : {}) }), () => { toast('success', 'Change request decided'); reload() })
        }} />
      {force.dialog}
      {sel && <AdminBookingModal bookingId={sel} onClose={() => setSel(null)} onChanged={reload} />}
    </div>
  )
}
