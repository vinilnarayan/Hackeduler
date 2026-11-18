import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { get } from '../../api/client'
import { shiftMonth } from '../../components/MyMonthCalendar'
import { ErrorState, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { fmt, initials } from '../../lib/dates'
import { useAsync } from '../../lib/useAsync'

interface Entry { booking_id: string; resource_id: string; resource_name: string; engineer_name: string; application_name: string; application_version: string; activity_name: string; status: string; tentative: boolean; start_date: string | null; end_date: string | null }
interface LeaveE { leave_id: string; resource_id: string; resource_name: string; engineer_name: string; leave_type: string | null }
interface FreeE { resource_id: string; resource_name: string; engineer_name: string }
interface Day { date: string; in_month: boolean; weekend: boolean; holiday: string | null; entries: Entry[]; leaves: LeaveE[]; free: FreeE[] }
interface Res { id: string; display_name: string; engineer_name: string; is_active: boolean }
interface Cal { month: string; today: string; days: Day[]; resources: Res[]; summary: { working_days: number; booked_days: number; leave_days: number; holidays: number } }

const COLOURS = ['bg-blue-100 text-blue-900 ring-blue-300', 'bg-violet-100 text-violet-900 ring-violet-300', 'bg-teal-100 text-teal-900 ring-teal-300',
  'bg-fuchsia-100 text-fuchsia-900 ring-fuchsia-300', 'bg-orange-100 text-orange-900 ring-orange-300', 'bg-cyan-100 text-cyan-900 ring-cyan-300',
  'bg-lime-100 text-lime-900 ring-lime-300', 'bg-rose-100 text-rose-900 ring-rose-300']
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MAX_SHOWN = 4
const monthLabel = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const statusLabel = (s: string) => s.replace(/_/g, ' ')

export default function TeamCalendar() {
  const [month, setMonth] = useState<string | undefined>(undefined)
  const [resource, setResource] = useState('')
  const [picked, setPicked] = useState<string | null>(null)
  const { data, error, loading, reload } = useAsync<Cal>(
    () => get('/api/admin/team-calendar' + (month || resource ? '?' + [month && `month=${month}`, resource && `resource_id=${resource}`].filter(Boolean).join('&') : '')), [month, resource])
  if (error) return <ErrorState message={error} onRetry={reload} />
  const cur = data?.month ?? month
  const colour = (id: string) => COLOURS[Math.max(0, data?.resources.findIndex((r) => r.id === id) ?? 0) % COLOURS.length]
  const day = data?.days.find((d) => d.date === picked) ?? null
  const s = data?.summary
  return (
    <div>
      <PageHeader title="Team Calendar" subtitle="Every resource's activity, leave and the holidays, day by day. Click a day for the details." />
      <section className="card p-4" aria-label="Team calendar">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-2 text-base font-semibold">{cur ? monthLabel(cur) : 'Calendar'}</h2>
          <button className="btn-secondary" aria-label="Previous month" disabled={!cur} onClick={() => cur && setMonth(shiftMonth(cur, -1))}><ChevronLeft className="h-4 w-4" /></button>
          <button className="btn-secondary" aria-label="Next month" disabled={!cur} onClick={() => cur && setMonth(shiftMonth(cur, 1))}><ChevronRight className="h-4 w-4" /></button>
          <button className="btn-secondary" onClick={() => setMonth(undefined)}>Today</button>
          <label className="ml-auto flex items-center gap-2 text-sm"><span>Resource</span>
            <select className="input w-52" aria-label="Resource" value={resource} onChange={(e) => setResource(e.target.value)}>
              <option value="">All resources</option>
              {data?.resources.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}</option>)}
            </select>
          </label>
        </div>
        {s && <div className="mb-3 flex flex-wrap gap-1.5 text-xs">
          <span className="rounded-full bg-blue-100 px-2 py-0.5 font-medium text-blue-900">Activity days {s.booked_days}</span>
          <span className="rounded-full bg-sky-100 px-2 py-0.5 font-medium text-sky-900">Leave days {s.leave_days}</span>
          <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-900">Holidays {s.holidays}</span>
        </div>}
        {loading && !data ? <Spinner /> : data && (
          <div className="overflow-x-auto">
            <div role="grid" aria-label={monthLabel(data.month)} className="grid min-w-[860px] grid-cols-7 gap-1">
              {WEEKDAYS.map((w) => <div key={w} role="columnheader" className="px-1 pb-1 text-center text-xs font-medium text-slate-500">{w}</div>)}
              {data.days.map((d) => {
                const shown = d.entries.slice(0, MAX_SHOWN)
                const more = d.entries.length - shown.length
                const isToday = d.date === data.today
                return (
                  <div key={d.date} role="gridcell" tabIndex={0} data-date={d.date} aria-label={`${d.date}: ${d.entries.length} activities, ${d.leaves.length} on leave${d.holiday ? `, ${d.holiday}` : ''}`}
                    onClick={() => setPicked(d.date)} onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setPicked(d.date) } }}
                    className={`flex min-h-28 cursor-pointer flex-col gap-0.5 rounded-md p-1.5 text-[11px] ring-1 hover:brightness-95 ${d.holiday ? 'bg-amber-50 ring-amber-300' : d.weekend ? 'bg-slate-100 ring-slate-200' : 'bg-white ring-slate-200'}${d.in_month ? '' : ' opacity-40'}${isToday ? ' outline outline-2 outline-offset-1 outline-blue-600' : ''}`}>
                    <div className={`text-xs font-semibold ${isToday ? 'text-blue-700' : ''}`}>{Number(d.date.slice(8))}</div>
                    {d.holiday && <span className="truncate font-medium text-amber-800" title={d.holiday}>{d.holiday}</span>}
                    {shown.map((e) => (
                      <span key={e.booking_id + e.resource_id} title={`${e.engineer_name} (${e.resource_name}) - ${e.application_name} v${e.application_version} - ${e.activity_name} [${statusLabel(e.status)}]`}
                        className={`truncate rounded px-1 py-0.5 ring-1 ${colour(e.resource_id)}${e.tentative ? ' border border-dashed border-slate-500' : ''}`}>
                        <b>{initials(e.engineer_name, e.resource_name.replace(/^Resource /, 'R'))}</b> {e.application_name}{e.application_version ? ` v${e.application_version}` : ''}
                      </span>
                    ))}
                    {more > 0 && <span className="font-medium text-slate-600">+{more} more</span>}
                    {d.leaves.map((l) => <span key={l.leave_id + d.date} className="truncate rounded bg-sky-200 px-1 py-0.5 font-medium text-sky-900" title={`${l.resource_name} (${l.engineer_name}) on leave`}><b>{initials(l.engineer_name, l.resource_name.replace(/^Resource /, 'R'))}</b> leave</span>)}
                  </div>
                )
              })}
            </div>
          </div>
        )}
        <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
          <span><span className="mr-1 inline-block h-3 w-3 rounded-sm bg-blue-100 ring-1 ring-blue-300" />Activity (colour = resource)</span>
          <span><span className="mr-1 inline-block h-3 w-3 rounded-sm border border-dashed border-slate-500 bg-white" />Dashed = pending approval</span>
          <span><span className="mr-1 inline-block h-3 w-3 rounded-sm bg-sky-200" />Leave</span>
          <span><span className="mr-1 inline-block h-3 w-3 rounded-sm bg-amber-50 ring-1 ring-amber-300" />Holiday</span>
          <span><span className="mr-1 inline-block h-3 w-3 rounded-sm bg-slate-100 ring-1 ring-slate-300" />Weekend</span>
        </p>
      </section>
      <Modal open={!!day} onClose={() => setPicked(null)} title={day ? fmt(day.date, 'EEEE, dd MMM yyyy') : ''} size="lg" footer={<button className="btn-secondary" onClick={() => setPicked(null)}>Close</button>}>
        {day && <div className="space-y-4 text-sm">
          {day.holiday && <p className="rounded bg-amber-50 px-3 py-2 text-amber-900">Holiday: {day.holiday}</p>}
          {day.weekend && !day.holiday && <p className="text-slate-500">Non-working day.</p>}
          <section aria-label="Activities">
            <h3 className="mb-1 font-semibold">Activities</h3>
            {day.entries.length === 0 ? <p className="text-slate-500">No activity on this day.</p> : (
              <ul className="divide-y divide-slate-100 rounded border border-slate-200">
                {day.entries.map((e) => (
                  <li key={e.booking_id + e.resource_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ring-1 ${colour(e.resource_id)}`}>{e.resource_name}</span>
                    <span className="text-xs text-slate-500">{e.engineer_name}</span>
                    <span className="font-medium">{e.application_name} v{e.application_version}</span>
                    <span>{e.activity_name}</span>
                    <span className="text-xs text-slate-500">{fmt(e.start_date)} – {fmt(e.end_date)}</span>
                    <Pill>{statusLabel(e.status)}</Pill>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-label="Free">
            <h3 className="mb-1 font-semibold">Free{day.free.length > 0 ? ` (${day.free.length})` : ''}</h3>
            {day.weekend || day.holiday ? <p className="text-slate-500">Non-working day – nobody is scheduled.</p>
              : day.free.length === 0 ? <p className="text-slate-500">Nobody is free on this day.</p> : (
                <ul className="divide-y divide-slate-100 rounded border border-slate-200">
                  {day.free.map((f) => <li key={f.resource_id} className="flex flex-wrap items-center gap-x-3 px-3 py-2"><span className={`rounded px-1.5 py-0.5 text-xs font-semibold ring-1 ${colour(f.resource_id)}`}>{f.resource_name}</span><span className="text-xs text-slate-500">{f.engineer_name}</span><span className="text-emerald-700">Free</span></li>)}
                </ul>
              )}
          </section>
          <section aria-label="Leave">
            <h3 className="mb-1 font-semibold">On leave</h3>
            {day.leaves.length === 0 ? <p className="text-slate-500">Nobody is on leave.</p> : (
              <ul className="divide-y divide-slate-100 rounded border border-slate-200">
                {day.leaves.map((l) => <li key={l.leave_id} className="flex flex-wrap items-center gap-x-3 px-3 py-2"><span className="font-medium">{l.resource_name}</span><span className="text-xs text-slate-500">{l.engineer_name}</span><span>{l.leave_type ?? 'Leave'}</span></li>)}
              </ul>
            )}
          </section>
        </div>}
      </Modal>
    </div>
  )
}
