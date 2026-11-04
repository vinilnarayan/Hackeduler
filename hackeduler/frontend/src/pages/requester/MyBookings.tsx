import { useState } from 'react'
import { Search } from 'lucide-react'
import { get, post, qs, validationMessage } from '../../api/client'
import type { Booking, BookingStatus } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, KV, Modal, PageHeader, Spinner, StatusBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { STATUS_LABELS } from '../../lib/status'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

const TABS: { key: '' | BookingStatus; label: string }[] = [
  { key: '', label: 'All' }, { key: 'pending_approval', label: 'Pending' }, { key: 'approved', label: 'Approved' },
  { key: 'completed', label: 'Completed' }, { key: 'rejected', label: 'Rejected' }, { key: 'cancelled', label: 'Cancelled' }, { key: 'expired', label: 'Expired' },
]

export default function MyBookings() {
  const [tab, setTab] = useState<'' | BookingStatus>('')
  const [q, setQ] = useState('')
  const [sel, setSel] = useState<Booking | null>(null)
  const { data, error, loading, reload } = useAsync<Booking[]>(() => get('/api/bookings/mine' + qs({ status: tab, q })), [tab, q])
  return (
    <div>
      <PageHeader title="My Bookings" subtitle="Only your own booking requests are shown." />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap rounded-md border border-slate-300 bg-white p-0.5" role="tablist">
          {TABS.map((t) => <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)} className={`rounded px-3 py-1 text-sm ${tab === t.key ? 'bg-blue-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`}>{t.label}</button>)}
        </div>
        <label className="relative ml-auto"><span className="sr-only">Search applications</span><Search className="absolute top-2 left-2 h-4 w-4 text-slate-400" /><input className="input w-64 pl-8" placeholder="Search application…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.length ? <Empty title="No bookings found" hint="Create a new booking request from the calendar." /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Application</th><th className="th">Activity</th><th className="th">Resource</th><th className="th">Dates</th><th className="th">Status</th><th className="th">Submitted</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((b) => (
                <tr key={b.id} className="cursor-pointer hover:bg-slate-50" tabIndex={0} onClick={() => setSel(b)} onKeyDown={(e) => e.key === 'Enter' && setSel(b)}>
                  <td className="td"><div className="font-medium">{b.application_name}</div><div className="text-xs text-slate-500">v{b.application_version} · <span className="font-mono">{b.id.slice(0, 8)}</span></div></td>
                  <td className="td">{b.activity_name}<div className="text-xs text-slate-500">{b.duration_days} working days</div></td>
                  <td className="td">{b.resource_display_name}</td>
                  <td className="td whitespace-nowrap">{fmt(b.start_date)} – {fmt(b.end_date)}</td>
                  <td className="td"><StatusBadge status={b.status} />{b.pending_change_request && <div className="mt-1 text-xs text-amber-700">Change requested</div>}</td>
                  <td className="td text-xs text-slate-500">{fmtDateTime(b.submitted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {sel && <BookingDetail booking={sel} onClose={() => setSel(null)} onChanged={() => { setSel(null); reload() }} />}
    </div>
  )
}

function BookingDetail({ booking: b, onClose, onChanged }: { booking: Booking; onClose: () => void; onChanged: () => void }) {
  const toast = useToast()
  const hist = useAsync<any>(() => get(`/api/bookings/${b.id}/history`), [b.id])
  const settings = useAsync<any>(() => get('/api/settings/public'))
  const [mode, setMode] = useState<null | 'cancel' | 'reschedule'>(null)
  const [newStart, setNewStart] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const active = b.status === 'pending_approval' || b.status === 'approved'
  const directCancel = b.status === 'pending_approval' && settings.data?.requester_direct_cancel_pending

  async function cancelDirect(r: string) {
    try { await post(`/api/bookings/${b.id}/cancel`, { reason: r }); toast('success', 'Booking cancelled; reservation released'); onChanged() }
    catch (e) { toast('error', validationMessage(e)) }
  }
  async function requestChange() {
    setBusy(true)
    try {
      const r = await post<any>(`/api/bookings/${b.id}/change-requests`, { request_type: mode, reason, proposed_start_date: mode === 'reschedule' ? newStart : null })
      if (r.preview && !r.preview.available) toast('info', 'Request submitted. Note: the proposed dates currently show a conflict; the admin will review alternatives.')
      else toast('success', mode === 'cancel' ? 'Cancellation request submitted' : `Reschedule request submitted${r.preview?.end_date ? ` (new end date would be ${fmt(r.preview.end_date)})` : ''}`)
      onChanged()
    } catch (e) { toast('error', validationMessage(e)) } finally { setBusy(false) }
  }

  return (
    <Modal open onClose={onClose} size="lg" title={<span>{b.application_name} <span className="ml-1 align-middle"><StatusBadge status={b.status} /></span></span>}
      footer={active && !b.pending_change_request ? <>
        {directCancel ? <button className="btn-danger" onClick={() => setMode('cancel')}>Cancel request</button> : <button className="btn-secondary" onClick={() => setMode('cancel')}>Request cancellation</button>}
        <button className="btn-secondary" onClick={() => setMode('reschedule')}>Request reschedule</button>
      </> : undefined}>
      <div className="space-y-4">
        <KV items={[
          ['Booking ID', <span className="font-mono text-xs break-all">{b.id}</span>], ['Resource', b.resource_display_name],
          ['Activity', `${b.activity_name} (${b.duration_days} working days)`], ['Application version', b.application_version],
          ['Start date', fmt(b.start_date)], ['Expected end date', fmt(b.end_date)], ['PCI DSS scope', b.pci_dss_scope ? 'Yes' : 'No'],
          ['POC', `${b.poc_name} <${b.poc_email}>`], ['Submitted', fmtDateTime(b.submitted_at)],
          ...(b.expires_at && b.status === 'pending_approval' ? [['Reservation held until', fmtDateTime(b.expires_at)] as [string, string]] : []),
          ...(b.rejection_reason ? [['Rejection reason', b.rejection_reason] as [string, string]] : []),
          ...(b.cancellation_reason ? [['Cancellation reason', b.cancellation_reason] as [string, string]] : []),
          ...(b.additional_comments ? [['Comments', b.additional_comments] as [string, string]] : []),
        ]} />
        {b.pending_change_request && <div className="rounded border border-amber-300 bg-amber-50 p-2 text-sm">A {b.pending_change_request.request_type} request is awaiting admin review{b.pending_change_request.proposed_start_date ? ` (proposed start ${fmt(b.pending_change_request.proposed_start_date)})` : ''}.</div>}
        {mode && !(mode === 'cancel' && directCancel) && (
          <div className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3">
            <div className="text-sm font-semibold">{mode === 'cancel' ? 'Request cancellation' : 'Request reschedule'}</div>
            {mode === 'reschedule' && <Field label="Proposed new start date *" htmlFor="ns"><input id="ns" type="date" className="input w-48" value={newStart} onChange={(e) => setNewStart(e.target.value)} /></Field>}
            <Field label="Reason *" htmlFor="rr"><textarea id="rr" className="input min-h-16" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} /></Field>
            <div className="flex gap-2"><button className="btn-secondary" onClick={() => setMode(null)}>Back</button><button className="btn-primary" disabled={busy || !reason.trim() || (mode === 'reschedule' && !newStart)} onClick={requestChange}>Submit request</button></div>
          </div>
        )}
        <div>
          <div className="label">History</div>
          {hist.loading ? <Spinner /> : (
            <ol className="relative space-y-2 border-l border-slate-200 pl-4 text-sm">
              {hist.data?.events.map((e: any, i: number) => (
                <li key={i}><div className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border-2 border-white bg-blue-600" />
                  <div className="text-xs text-slate-500">{fmtDateTime(e.at)}</div>
                  <div>{e.type === 'status' ? <>Status → <span className="font-medium">{STATUS_LABELS[e.to_status as BookingStatus] ?? e.to_status}</span></> : e.type === 'change_request' ? <>Requested {e.request_type}{e.proposed_start_date ? ` (start ${fmt(e.proposed_start_date)})` : ''}</> : <>Change request {e.status}</>}</div>
                  {e.note && <div className="text-xs text-slate-600">{e.note}</div>}
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
      <ConfirmDialog open={mode === 'cancel' && !!directCancel} title="Cancel booking request" tone="danger" confirmLabel="Cancel booking"
        message="Your pending reservation will be released immediately." requireReason reasonLabel="Reason for cancellation"
        onConfirm={cancelDirect} onClose={() => setMode(null)} />
    </Modal>
  )
}
