import { Link, useNavigate } from 'react-router-dom'
import { CalendarCheck, CalendarPlus, Clock, Server, XCircle } from 'lucide-react'
import { get } from '../../api/client'
import type { ActivityType, Booking } from '../../api/types'
import { ResourceCalendar } from '../../components/ResourceCalendar'
import { Empty, ErrorState, PageHeader, Spinner, StatCard, StatusBadge } from '../../components/ui'
import { fmt } from '../../lib/dates'
import { useAsync } from '../../lib/useAsync'

export default function RequesterDashboard() {
  const nav = useNavigate()
  const { data, error, loading, reload } = useAsync<any>(() => get('/api/me/dashboard'))
  const acts = useAsync<ActivityType[]>(() => get('/api/activity-types'))
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <Spinner />
  const c = data.counts
  return (
    <div className="space-y-6">
      <PageHeader title="Welcome" subtitle={`Today is ${fmt(data.today, 'EEEE, dd MMM yyyy')}`}
        actions={<Link to="/book" className="btn-primary"><CalendarPlus className="h-4 w-4" /> New booking request</Link>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Resources available today" value={`${data.available_resources_today}/${data.active_resources}`} icon={<Server className="h-5 w-5" />} tone="green" />
        <StatCard label="My pending requests" value={c.pending_approval} icon={<Clock className="h-5 w-5" />} tone="blue" />
        <StatCard label="My approved bookings" value={c.approved + c.completed} icon={<CalendarCheck className="h-5 w-5" />} tone="green" />
        <StatCard label="Rejected / cancelled / expired" value={c.rejected + c.cancelled + c.expired} icon={<XCircle className="h-5 w-5" />} tone="red" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <div className="border-b border-slate-200 px-4 py-2 text-sm font-semibold">Upcoming scheduled assessments</div>
          {data.upcoming.length === 0 ? <Empty title="No upcoming approved assessments" hint="Approved bookings will appear here." /> : (
            <ul className="divide-y divide-slate-100">
              {data.upcoming.map((b: Booking) => (
                <li key={b.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
                  <div className="flex-1"><div className="font-medium">{b.application_name} <span className="text-slate-500">v{b.application_version}</span></div><div className="text-xs text-slate-500">{b.activity_name} · {b.resource_display_name}</div></div>
                  <div className="text-xs whitespace-nowrap">{fmt(b.start_date)} – {fmt(b.end_date)}</div>
                  <StatusBadge status={b.status} />
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <div className="border-b border-slate-200 px-4 py-2 text-sm font-semibold">Upcoming holidays (30 days)</div>
          {data.upcoming_holidays.length === 0 ? <Empty title="No holidays in the next 30 days" /> : (
            <ul className="divide-y divide-slate-100 text-sm">{data.upcoming_holidays.map((h: any) => <li key={h.date} className="flex justify-between px-4 py-2"><span>{h.name}</span><span className="text-slate-500">{fmt(h.date)}</span></li>)}</ul>
          )}
        </div>
      </div>
      <div>
        <h2 className="mb-2 text-base font-semibold">Resource availability</h2>
        <ResourceCalendar mode="requester" initialView="week" activityTypes={acts.data ?? []}
          onCellClick={(r, cell) => cell.mine ? nav('/my-bookings') : nav(`/book?resource=${r.id}&start=${cell.date}`)} />
      </div>
    </div>
  )
}
