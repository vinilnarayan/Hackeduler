import { Link } from 'react-router-dom'
import { CalendarClock, CheckCircle2, ClipboardList, FileCheck2, FileWarning, Plane, PlayCircle } from 'lucide-react'
import { get } from '../../api/client'
import type { Booking } from '../../api/types'
import { Empty, ErrorState, PageHeader, ReportBadge, Spinner, StatCard } from '../../components/ui'
import { fmt } from '../../lib/dates'
import { useAsync } from '../../lib/useAsync'

function BookingList({ title, items, empty }: { title: string; items: Booking[]; empty: string }) {
  return (
    <div className="card">
      <div className="border-b border-slate-200 px-4 py-2 text-sm font-semibold">{title}</div>
      {items.length === 0 ? <Empty title={empty} /> : (
        <ul className="divide-y divide-slate-100">{items.map((b) => (
          <li key={b.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
            <div className="min-w-0 flex-1"><div className="font-medium">{b.application_name} <span className="text-slate-500">v{b.application_version}</span></div><div className="text-xs text-slate-500">{b.activity_name}</div></div>
            <div className="text-xs whitespace-nowrap">{fmt(b.start_date)} – {fmt(b.end_date)}</div>
            <ReportBadge shared={b.report_shared} type={b.report_type} />
          </li>
        ))}</ul>
      )}
    </div>
  )
}

export default function ResourceDashboard() {
  const { data, error, loading, reload } = useAsync<any>(() => get('/api/resource/dashboard'))
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <Spinner />
  const c = data.counts
  return (
    <div className="space-y-6">
      <PageHeader title="My dashboard" subtitle={`Assignments and leave for ${data.resource.display_name ?? 'your resource'}`}
        actions={<Link to="/assignments" className="btn-primary"><ClipboardList className="h-4 w-4" />My assignments</Link>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Assigned bookings" value={c.assigned} icon={<ClipboardList className="h-5 w-5" />} tone="blue" />
        <StatCard label="In progress now" value={c.in_progress} icon={<PlayCircle className="h-5 w-5" />} tone="green" />
        <StatCard label="Upcoming" value={c.upcoming} icon={<CalendarClock className="h-5 w-5" />} tone="violet" />
        <StatCard label="Completed" value={c.completed} icon={<CheckCircle2 className="h-5 w-5" />} tone="slate" />
        <StatCard label="Reports shared" value={c.reports_shared} icon={<FileCheck2 className="h-5 w-5" />} tone="green" hint={`${c.reports_v1} V1 · ${c.reports_met} Met`} />
        <StatCard label="Reports to share" value={c.reports_pending} icon={<FileWarning className="h-5 w-5" />} tone="amber" hint="Finished work, report not yet shared" />
        <StatCard label="Upcoming leaves" value={c.upcoming_leaves} icon={<Plane className="h-5 w-5" />} tone="blue" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <BookingList title="In progress" items={data.in_progress} empty="Nothing in progress today" />
        <BookingList title="Upcoming assignments" items={data.upcoming} empty="No upcoming assignments" />
        <BookingList title="Reports waiting to be shared" items={data.reports_pending} empty="All reports are shared" />
        <div className="card">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2 text-sm font-semibold">Upcoming leave<Link to="/leaves" className="text-xs font-normal text-blue-700">Manage</Link></div>
          {data.leaves.length === 0 ? <Empty title="No upcoming leave" /> : (
            <ul className="divide-y divide-slate-100">{data.leaves.map((l: any) => (
              <li key={l.id} className="flex items-center justify-between px-4 py-2 text-sm"><span>{fmt(l.start_date)} – {fmt(l.end_date)}</span><span className="text-xs text-slate-500">{l.leave_type ?? ''}</span></li>
            ))}</ul>
          )}
        </div>
      </div>
    </div>
  )
}
