import { useState } from 'react'
import { Search } from 'lucide-react'
import { get, qs } from '../../api/client'
import type { Booking } from '../../api/types'
import { ReportEditor } from '../../components/ReportEditor'
import { Empty, ErrorState, KV, Modal, PageHeader, ReportBadge, Spinner, StatusBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { useAsync } from '../../lib/useAsync'

type Row = Booking & { requester_email?: string | null; extra_resources?: string[] }

export default function Assignments() {
  const [q, setQ] = useState('')
  const [report, setReport] = useState('')
  const [status, setStatus] = useState('')
  const [sel, setSel] = useState<string | null>(null)
  const { data, error, loading, reload } = useAsync<{ total: number; items: Row[] }>(() => get('/api/resource/bookings' + qs({ q, report, status })), [q, report, status])
  const current = data?.items.find((b) => b.id === sel) ?? null
  return (
    <div>
      <PageHeader title="My assignments" subtitle="Bookings assigned to you. Open one to record whether the report has been shared." />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="relative"><Search className="absolute top-2.5 left-2.5 h-4 w-4 text-slate-400" /><input className="input w-64 pl-8" placeholder="Search application, version, POC" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <select className="input w-44" aria-label="Report filter" value={report} onChange={(e) => setReport(e.target.value)}><option value="">All reports</option><option value="shared">Report shared</option><option value="pending">Not shared</option></select>
        <select className="input w-44" aria-label="Status filter" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option><option value="approved">Approved</option><option value="completed">Completed</option></select>
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No assignments" hint="Approved bookings for your resource appear here." /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Application</th><th className="th">Version</th><th className="th">Activity</th><th className="th">Dates</th><th className="th">POC</th><th className="th">Status</th><th className="th">Report</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.items.map((b) => (
              <tr key={b.id} tabIndex={0} className="cursor-pointer hover:bg-slate-50" onClick={() => setSel(b.id)} onKeyDown={(e) => e.key === 'Enter' && setSel(b.id)}>
                <td className="td font-medium">{b.application_name}</td><td className="td whitespace-nowrap">{b.application_version}</td><td className="td">{b.activity_name}</td>
                <td className="td whitespace-nowrap">{fmt(b.start_date)} – {fmt(b.end_date)}</td><td className="td text-xs">{b.poc_name}<div className="text-slate-500">{b.poc_email}</div></td>
                <td className="td"><StatusBadge status={b.status} /></td>
                <td className="td"><ReportBadge shared={b.report_shared} type={b.report_type} />{b.report_comments && <div className="mt-1 max-w-48 truncate text-xs text-slate-500" title={b.report_comments}>{b.report_comments}</div>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {current && (
        <Modal open onClose={() => setSel(null)} size="lg" title={<span>{current.application_name} <span className="ml-1 align-middle"><StatusBadge status={current.status} /></span></span>}>
          <div className="space-y-4">
            <KV items={[
              ['Application', `${current.application_name} v${current.application_version}`], ['Activity', current.duration_days ? `${current.activity_name} (${current.duration_days} working days)` : current.activity_name],
              ['Dates', `${fmt(current.start_date)} – ${fmt(current.end_date)}`], ['PCI DSS scope', current.pci_dss_scope ? 'Yes' : 'No'],
              ['Product', current.product_name ?? '—'], ['Implementation', current.implementation_name ?? '—'],
              ['Requested by', current.requester_name ?? '—'], ['POC', `${current.poc_name} <${current.poc_email}>`],
              ...((current.extra_resources?.length ? [['Also assigned', current.extra_resources.join(', ')]] : []) as [string, string][]),
              ...((current.additional_comments ? [['Requester comments', current.additional_comments]] : []) as [string, string][]),
              ['Submitted', fmtDateTime(current.submitted_at)],
            ]} />
            <ReportEditor key={`${current.id}-${current.report_shared}-${current.report_type}-${current.report_comments}`} booking={current} url={`/api/resource/bookings/${current.id}/report`} onSaved={() => reload()} />
          </div>
        </Modal>
      )}
    </div>
  )
}
