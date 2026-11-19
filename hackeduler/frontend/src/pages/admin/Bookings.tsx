import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, CalendarPlus, Download, Search } from 'lucide-react'
import { get, qs } from '../../api/client'
import type { ActivityType, AdminBooking, Product, ResourceAdmin } from '../../api/types'
import { AdminBookingModal } from '../../components/AdminBookingModal'
import { SortTh, type SortState } from '../../components/SortTh'
import { Empty, ErrorState, PageHeader, Pill, Spinner, StatusBadge, ReportBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { STATUS_LABELS } from '../../lib/status'
import { useAsync } from '../../lib/useAsync'

export default function AdminBookings() {
  const [sp, setSp] = useSearchParams()
  const f = { status: sp.get('status') ?? '', resource_id: sp.get('resource_id') ?? '', product_id: sp.get('product_id') ?? '', activity_type_id: sp.get('activity_type_id') ?? '', q: sp.get('q') ?? '', start: sp.get('start') ?? '', end: sp.get('end') ?? '', needs_review: sp.get('needs_review') ?? '', pci: sp.get('pci') ?? '', report: sp.get('report') ?? '', sort_by: sp.get('sort_by') ?? '', sort_dir: sp.get('sort_dir') ?? '' }
  // 'report' filter -> API params: shared / not_shared / V1 / Met
  const reportQs = f.report === 'shared' ? { report_shared: 'true' } : f.report === 'not_shared' ? { report_shared: 'false' } : f.report ? { report_shared: 'true', report_type: f.report } : {}
  const { report: _r, ...fApi } = f
  const set = (k: keyof typeof f, v: string) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); setSp(n, { replace: true }) }
  const [page, setPage] = useState(0)
  const sort: SortState | null = f.sort_by ? { key: f.sort_by, dir: f.sort_dir === 'desc' ? 'desc' : 'asc' } : null
  const toggleSort = (k: string) => {
    const n = new URLSearchParams(sp)
    if (!sort || sort.key !== k) { n.set('sort_by', k); n.set('sort_dir', 'asc') } else if (sort.dir === 'asc') { n.set('sort_dir', 'desc') } else { n.delete('sort_by'); n.delete('sort_dir') }
    setPage(0); setSp(n, { replace: true })
  }
  // The open booking lives in the address (?booking=<id>) so a link from the Team Calendar, or a copied address, opens its details.
  const sel = sp.get('booking')
  const setSel = (id: string | null) => { const n = new URLSearchParams(sp); if (id) n.set('booking', id); else n.delete('booking'); setSp(n, { replace: true }) }
  const PAGE = 50
  const { data, error, loading, reload } = useAsync<{ total: number; items: AdminBooking[]; summary?: { total: number; pci: number; non_pci: number; report_shared: number; report_not_shared: number } }>(() => get('/api/admin/bookings' + qs({ ...fApi, ...reportQs, limit: PAGE, offset: page * PAGE })), [sp.toString(), page])
  const resources = useAsync<ResourceAdmin[]>(() => get('/api/admin/resources'))
  const acts = useAsync<ActivityType[]>(() => get('/api/admin/activity-types'))
  const products = useAsync<Product[]>(() => get('/api/admin/products'))
  return (
    <div>
      <PageHeader title="Bookings" subtitle="Review, approve, reject, modify and reassign bookings."
        actions={<>
          <a className="btn-secondary" href={'/api/admin/reports/bookings.csv' + qs({ status: f.status, start: f.start, end: f.end, resource_id: f.resource_id, product_id: f.product_id, pci: f.pci, ...reportQs })}><Download className="h-4 w-4" />CSV</a>
          <a className="btn-secondary" href={'/api/admin/reports/bookings.xlsx' + qs({ status: f.status, start: f.start, end: f.end, resource_id: f.resource_id, product_id: f.product_id, pci: f.pci, ...reportQs })}><Download className="h-4 w-4" />Excel</a>
          <Link className="btn-primary" to="/admin/bookings/new"><CalendarPlus className="h-4 w-4" />Manual allocation</Link>
        </>} />
      <div className="mb-3 flex flex-wrap gap-2 text-sm" aria-live="polite" data-testid="booking-counts">
        <span className="card px-3 py-1.5"><b className="tabular-nums">{data?.summary?.total ?? data?.total ?? '…'}</b> {(data?.summary?.total ?? data?.total) === 1 ? 'booking' : 'bookings'}</span>
        <span className="card px-3 py-1.5">PCI <b className="tabular-nums">{data?.summary?.pci ?? '…'}</b> · Non-PCI <b className="tabular-nums">{data?.summary?.non_pci ?? '…'}</b></span>
        <span className="card px-3 py-1.5">Report shared <b className="tabular-nums">{data?.summary?.report_shared ?? '…'}</b> · Not shared <b className="tabular-nums">{data?.summary?.report_not_shared ?? '…'}</b></span>
      </div>
      <div className="card mb-3 grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className="relative sm:col-span-2"><span className="sr-only">Search</span><Search className="absolute top-2 left-2 h-4 w-4 text-slate-400" /><input className="input pl-8" placeholder="Booking ID, application, version, POC…" value={f.q} onChange={(e) => set('q', e.target.value)} /></label>
        <select className="input" aria-label="Status" value={f.status} onChange={(e) => set('status', e.target.value)}><option value="">All statuses</option>{Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select className="input" aria-label="Resource" value={f.resource_id} onChange={(e) => set('resource_id', e.target.value)}><option value="">All resources</option>{resources.data?.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}</option>)}</select>
        <select className="input" aria-label="Product" value={f.product_id} onChange={(e) => set('product_id', e.target.value)}><option value="">All products</option>{products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <select className="input" aria-label="Activity type" value={f.activity_type_id} onChange={(e) => set('activity_type_id', e.target.value)}><option value="">All activities</option>{acts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}{a.base_duration_days ? ` (${a.base_duration_days}d)` : ''}</option>)}</select>
        <input type="date" className="input" aria-label="From" value={f.start} onChange={(e) => set('start', e.target.value)} />
        <input type="date" className="input" aria-label="To" value={f.end} onChange={(e) => set('end', e.target.value)} />
        <select className="input" aria-label="Review flag" value={f.needs_review} onChange={(e) => set('needs_review', e.target.value)}><option value="">Any review state</option><option value="true">Needs review</option><option value="false">No review flag</option></select>
        <select className="input" aria-label="PCI DSS scope" value={f.pci} onChange={(e) => set('pci', e.target.value)}><option value="">Any PCI scope</option><option value="true">PCI in scope</option><option value="false">Not PCI</option></select>
        <select className="input" aria-label="Report" value={f.report} onChange={(e) => set('report', e.target.value)}><option value="">Any report state</option><option value="shared">Report shared</option><option value="not_shared">Report not shared</option><option value="V1">Shared – V1</option><option value="Met">Shared – Met</option></select>
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No bookings match the filters" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><SortTh label="Booking" k="id" sort={sort} onToggle={toggleSort} /><SortTh label="Application" k="application" sort={sort} onToggle={toggleSort} /><SortTh label="Version" k="version" sort={sort} onToggle={toggleSort} /><SortTh label="Product" k="product" sort={sort} onToggle={toggleSort} /><SortTh label="Activity" k="activity" sort={sort} onToggle={toggleSort} /><SortTh label="PCI" k="pci" sort={sort} onToggle={toggleSort} /><SortTh label="Resource / Engineer" k="resource" sort={sort} onToggle={toggleSort} /><SortTh label="Dates" k="dates" sort={sort} onToggle={toggleSort} /><SortTh label="POC" k="poc" sort={sort} onToggle={toggleSort} /><SortTh label="Requester" k="requester" sort={sort} onToggle={toggleSort} /><SortTh label="Submitted" k="submitted" sort={sort} onToggle={toggleSort} /><SortTh label="Status" k="status" sort={sort} onToggle={toggleSort} /><SortTh label="Report" k="report" sort={sort} onToggle={toggleSort} /></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((b) => (
                <tr key={b.id} tabIndex={0} className="cursor-pointer hover:bg-slate-50" onClick={() => setSel(b.id)} onKeyDown={(e) => e.key === 'Enter' && setSel(b.id)}>
                  <td className="td font-mono text-xs" title={b.id}>{b.id.slice(0, 8)}…</td>
                  <td className="td"><div className="font-medium">{b.application_name}</div></td>
                  <td className="td whitespace-nowrap">{b.application_version}</td>
                  <td className="td text-xs">{b.product_name ?? <span className="text-slate-400">—</span>}{b.implementation_name && <div className="text-slate-500">{b.implementation_name}</div>}</td>
                  <td className="td">{b.activity_name}<div className="text-xs text-slate-500">{b.duration_days ? `${b.duration_days}d` : 'no duration'}</div></td>
                  <td className="td">{b.pci_dss_scope ? 'Yes' : 'No'}</td>
                  <td className="td">{b.requires_resource ? <>{b.resource_display_name}{b.extra_resources?.length > 0 && <span className="ml-1 rounded bg-blue-100 px-1 text-xs text-blue-800" title={b.extra_resources.map((r) => r.display_name).join(', ')}>+{b.extra_resources.length}</span>}<div className="text-xs text-slate-500">{b.engineer_name}</div></> : <span className="text-xs text-slate-500">Not required</span>}</td>
                  <td className="td whitespace-nowrap">{b.start_date ? <>{fmt(b.start_date)}<div className="text-xs text-slate-500">→ {fmt(b.end_date)}</div></> : <span className="text-xs text-slate-500">Date flexible</span>}</td>
                  <td className="td">{b.poc_name}<div className="text-xs text-slate-500">{b.poc_email}</div></td>
                  <td className="td text-xs">{b.requester_name}</td>
                  <td className="td text-xs whitespace-nowrap">{fmtDateTime(b.submitted_at)}</td>
                  <td className="td"><StatusBadge status={b.status} /><div className="mt-1 flex flex-wrap gap-1">
                    {b.is_force_allocated && <Pill className="bg-red-100 text-red-800">Forced</Pill>}
                    {b.needs_review && <Pill className="bg-amber-100 text-amber-800"><AlertTriangle className="h-3 w-3" />Review</Pill>}
                    {b.pending_change_request && <Pill className="bg-violet-100 text-violet-800">Change req.</Pill>}
                  </div></td>
                  <td className="td"><ReportBadge shared={b.report_shared} type={b.report_type} />{b.report_comments && <div className="mt-1 max-w-48 truncate text-xs text-slate-500" title={b.report_comments}>{b.report_comments}</div>}</td>
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
