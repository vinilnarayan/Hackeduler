import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, CalendarPlus, Download, Search } from 'lucide-react'
import { get, qs } from '../../api/client'
import type { ActivityType, AdminBooking, ResourceAdmin } from '../../api/types'
import { AdminBookingModal } from '../../components/AdminBookingModal'
import { Empty, ErrorState, PageHeader, Pill, Spinner, StatusBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { STATUS_LABELS } from '../../lib/status'
import { useAsync } from '../../lib/useAsync'

export default function AdminBookings() {
  const [sp, setSp] = useSearchParams()
  const f = { status: sp.get('status') ?? '', resource_id: sp.get('resource_id') ?? '', activity_type_id: sp.get('activity_type_id') ?? '', q: sp.get('q') ?? '', start: sp.get('start') ?? '', end: sp.get('end') ?? '', needs_review: sp.get('needs_review') ?? '', pci: sp.get('pci') ?? '' }
  const set = (k: keyof typeof f, v: string) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); setSp(n, { replace: true }) }
  const [page, setPage] = useState(0)
  const [sel, setSel] = useState<string | null>(null)
  const PAGE = 50
  const { data, error, loading, reload } = useAsync<{ total: number; items: AdminBooking[] }>(() => get('/api/admin/bookings' + qs({ ...f, limit: PAGE, offset: page * PAGE })), [sp.toString(), page])
  const resources = useAsync<ResourceAdmin[]>(() => get('/api/admin/resources'))
  const acts = useAsync<ActivityType[]>(() => get('/api/admin/activity-types'))
  return (
    <div>
      <PageHeader title="Bookings" subtitle="Review, approve, reject, modify and reassign bookings."
        actions={<>
          <a className="btn-secondary" href={'/api/admin/reports/bookings.csv' + qs({ status: f.status, start: f.start, end: f.end, resource_id: f.resource_id })}><Download className="h-4 w-4" />CSV</a>
          <a className="btn-secondary" href={'/api/admin/reports/bookings.xlsx' + qs({ status: f.status, start: f.start, end: f.end, resource_id: f.resource_id })}><Download className="h-4 w-4" />Excel</a>
          <Link className="btn-primary" to="/admin/bookings/new"><CalendarPlus className="h-4 w-4" />Manual allocation</Link>
        </>} />
      <div className="card mb-3 grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
        <label className="relative sm:col-span-2"><span className="sr-only">Search</span><Search className="absolute top-2 left-2 h-4 w-4 text-slate-400" /><input className="input pl-8" placeholder="Booking ID, application, POC…" value={f.q} onChange={(e) => set('q', e.target.value)} /></label>
        <select className="input" aria-label="Status" value={f.status} onChange={(e) => set('status', e.target.value)}><option value="">All statuses</option>{Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select className="input" aria-label="Resource" value={f.resource_id} onChange={(e) => set('resource_id', e.target.value)}><option value="">All resources</option>{resources.data?.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}</option>)}</select>
        <select className="input" aria-label="Activity type" value={f.activity_type_id} onChange={(e) => set('activity_type_id', e.target.value)}><option value="">All activities</option>{acts.data?.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.base_duration_days}d)</option>)}</select>
        <input type="date" className="input" aria-label="From" value={f.start} onChange={(e) => set('start', e.target.value)} />
        <input type="date" className="input" aria-label="To" value={f.end} onChange={(e) => set('end', e.target.value)} />
        <select className="input" aria-label="Review flag" value={f.needs_review} onChange={(e) => set('needs_review', e.target.value)}><option value="">Any review state</option><option value="true">Needs review</option><option value="false">No review flag</option></select>
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No bookings match the filters" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Booking</th><th className="th">Application</th><th className="th">Activity</th><th className="th">PCI</th><th className="th">Resource / Engineer</th><th className="th">Dates</th><th className="th">POC</th><th className="th">Requester</th><th className="th">Submitted</th><th className="th">Status</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((b) => (
                <tr key={b.id} tabIndex={0} className="cursor-pointer hover:bg-slate-50" onClick={() => setSel(b.id)} onKeyDown={(e) => e.key === 'Enter' && setSel(b.id)}>
                  <td className="td font-mono text-xs" title={b.id}>{b.id.slice(0, 8)}…</td>
                  <td className="td"><div className="font-medium">{b.application_name}</div><div className="text-xs text-slate-500">v{b.application_version}</div></td>
                  <td className="td">{b.activity_name}<div className="text-xs text-slate-500">{b.duration_days}d</div></td>
                  <td className="td">{b.pci_dss_scope ? 'Yes' : 'No'}</td>
                  <td className="td">{b.resource_display_name}<div className="text-xs text-slate-500">{b.engineer_name}</div></td>
                  <td className="td whitespace-nowrap">{fmt(b.start_date)}<div className="text-xs text-slate-500">→ {fmt(b.end_date)}</div></td>
                  <td className="td">{b.poc_name}<div className="text-xs text-slate-500">{b.poc_email}</div></td>
                  <td className="td text-xs">{b.requester_name}</td>
                  <td className="td text-xs whitespace-nowrap">{fmtDateTime(b.submitted_at)}</td>
                  <td className="td"><StatusBadge status={b.status} /><div className="mt-1 flex flex-wrap gap-1">
                    {b.is_force_allocated && <Pill className="bg-red-100 text-red-800">Forced</Pill>}
                    {b.needs_review && <Pill className="bg-amber-100 text-amber-800"><AlertTriangle className="h-3 w-3" />Review</Pill>}
                    {b.pending_change_request && <Pill className="bg-violet-100 text-violet-800">Change req.</Pill>}
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && data.total > PAGE && (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm"><span className="text-slate-500">{page * PAGE + 1}–{Math.min((page + 1) * PAGE, data.total)} of {data.total}</span>
          <button className="btn-secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="btn-secondary" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>Next</button></div>
      )}
      {sel && <AdminBookingModal bookingId={sel} onClose={() => setSel(null)} onChanged={reload} />}
    </div>
  )
}
