import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { get } from '../api/client'
import { CalendarDayDialog, type DayInfo, type DayNote } from './CalendarDayDialog'
import { ErrorState, Spinner } from './ui'
import { useAsync } from '../lib/useAsync'

type State = 'booked' | 'conflict' | 'leave' | 'holiday' | 'weekend' | 'tentative' | 'free'
interface Day extends DayInfo { in_month: boolean; state: State; notes: DayNote[] }
interface CalBooking { id: string; application_name: string; application_version: string; activity_name: string; start_date: string; end_date: string; report_shared: boolean; report_type: string | null }
interface Cal { month: string; today: string; days: Day[]; bookings: Record<string, CalBooking>; leave_types: string[]; personal_leave: { year: number; limit: number; used: number }; summary: { working_days: number; booked: number; leave: number; free: number; tentative: number; holidays: number; conflicts: number } }

// One colour per booking (fill + text), so the days of the same activity read as one block.
const PALETTE = [
  'bg-blue-100 text-blue-900 ring-blue-300', 'bg-violet-100 text-violet-900 ring-violet-300', 'bg-teal-100 text-teal-900 ring-teal-300',
  'bg-fuchsia-100 text-fuchsia-900 ring-fuchsia-300', 'bg-orange-100 text-orange-900 ring-orange-300', 'bg-cyan-100 text-cyan-900 ring-cyan-300',
]
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const shiftMonth = (month: string, by: number) => {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + by, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}
const monthLabel = (month: string) => new Date(`${month}-01T00:00:00Z`).toLocaleString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })

function Legend() {
  const items: [string, string][] = [['bg-blue-100 ring-1 ring-blue-300', 'Assigned activity'], ['bg-emerald-50 ring-1 ring-emerald-300', 'Free'], ['bg-sky-100 ring-1 ring-sky-300', 'My leave'],
    ['bg-amber-50 ring-1 ring-amber-300', 'Holiday'], ['bg-slate-100 ring-1 ring-slate-300', 'Weekend'], ['bg-white ring-1 ring-slate-300 [background-image:repeating-linear-gradient(45deg,#e2e8f0,#e2e8f0_3px,transparent_3px,transparent_7px)]', 'On hold (request pending approval)'],
    ['bg-red-50 ring-2 ring-red-400', 'Leave clashes with an activity'], ['bg-yellow-100 ring-1 ring-yellow-300', 'Has a note']]
  return <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">{items.map(([c, l]) => <span key={l} className="inline-flex items-center gap-1.5"><span className={`inline-block h-3 w-3 rounded-sm ${c}`} />{l}</span>)}</div>
}

export function MyMonthCalendar() {
  const [month, setMonth] = useState<string | undefined>(undefined)
  const nav = useNavigate()
  const [picked, setPicked] = useState<string | null>(null)
  const { data, error, loading, reload } = useAsync<Cal>(() => get('/api/resource/calendar' + (month ? `?month=${month}` : '')), [month])
  if (error) return <ErrorState message={error} onRetry={reload} />
  const cur = data?.month ?? month
  const order = data ? Object.values(data.bookings).sort((a, b) => a.start_date.localeCompare(b.start_date)) : []
  const colour = (id: string) => PALETTE[Math.max(0, order.findIndex((b) => b.id === id)) % PALETTE.length]
  const s = data?.summary
  return (
    <section className="card p-4" aria-label="Monthly calendar">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-2 text-base font-semibold">{cur ? monthLabel(cur) : 'Calendar'}</h2>
        <button className="btn-secondary" aria-label="Previous month" disabled={!cur} onClick={() => cur && setMonth(shiftMonth(cur, -1))}><ChevronLeft className="h-4 w-4" /></button>
        <button className="btn-secondary" aria-label="Next month" disabled={!cur} onClick={() => cur && setMonth(shiftMonth(cur, 1))}><ChevronRight className="h-4 w-4" /></button>
        <button className="btn-secondary" onClick={() => setMonth(undefined)}>Today</button>
        {s && (
          <div className="ml-auto flex flex-wrap gap-1.5 text-xs">
            <span className="rounded-full bg-blue-100 px-2 py-0.5 font-medium text-blue-900">Assigned {s.booked} d</span>
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-900">Free {s.free} d</span>
            <span className="rounded-full bg-sky-100 px-2 py-0.5 font-medium text-sky-900">Leave {s.leave} d</span>
            <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-900">Holidays {s.holidays}</span>
            {s.tentative > 0 && <span className="rounded-full bg-slate-200 px-2 py-0.5 font-medium text-slate-700">On hold {s.tentative} d</span>}
            {s.conflicts > 0 && <span className="rounded-full bg-red-100 px-2 py-0.5 font-medium text-red-800">Clashes {s.conflicts}</span>}
          </div>
        )}
      </div>
      {loading && !data ? <Spinner /> : data && (
        <div className="overflow-x-auto">
          <div role="grid" aria-label={monthLabel(data.month)} className="grid min-w-[680px] grid-cols-7 gap-1">
            {WEEKDAYS.map((w) => <div key={w} role="columnheader" className="px-1 pb-1 text-center text-xs font-medium text-slate-500">{w}</div>)}
            {data.days.map((d) => {
              const num = Number(d.date.slice(8))
              const isToday = d.date === data.today
              const base = 'flex min-h-24 flex-col gap-1 rounded-md p-1.5 text-xs ring-1 '
              const tone: Record<State, string> = {
                booked: 'bg-white ring-slate-200', conflict: 'bg-red-50 ring-2 ring-red-400', leave: 'bg-sky-100 ring-sky-300',
                holiday: 'bg-amber-50 ring-amber-300', weekend: 'bg-slate-100 ring-slate-200 text-slate-400',
                tentative: 'bg-white ring-slate-300 [background-image:repeating-linear-gradient(45deg,#e2e8f0,#e2e8f0_3px,transparent_3px,transparent_7px)]',
                free: 'bg-emerald-50 ring-emerald-200',
              }
              const names = d.booking_ids.map((id) => data.bookings[id]?.application_name).filter(Boolean).join(', ')
              const label = `${d.date}: ${d.state === 'free' ? 'free' : d.state}${names ? ` - ${names}` : ''}${d.holiday ? ` - ${d.holiday}` : ''}${d.leave ? ' - on leave' : ''}`
              return (
                <div key={d.date} role="gridcell" tabIndex={0} aria-label={label} data-state={d.state} onClick={() => setPicked(d.date)}
                  onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setPicked(d.date) } }}
                  className={'cursor-pointer hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 ' + base + tone[d.state] + (d.in_month ? '' : ' opacity-40') + (isToday ? ' outline outline-2 outline-offset-1 outline-blue-600' : '')}>
                  <div className="flex items-center justify-between"><span className={`font-semibold ${isToday ? 'text-blue-700' : ''}`}>{num}</span>{d.state === 'free' && d.in_month && <span className="text-[10px] font-medium text-emerald-700">Free</span>}</div>
                  {d.booking_ids.map((id) => {
                    const b = data.bookings[id]
                    if (!b) return null
                    return (
                      <button key={id} type="button" title={`${b.application_name} v${b.application_version} - ${b.activity_name}\n${b.start_date} to ${b.end_date}${b.report_shared ? `\nReport shared (${b.report_type})` : ''}`}
                        onClick={(e) => { e.stopPropagation(); nav(`/assignments?booking=${id}`) }} className={`truncate rounded px-1 py-0.5 text-left font-medium ring-1 hover:brightness-95 ${colour(id)}`}>
                        {b.application_name}
                      </button>
                    )
                  })}
                  {d.leave && d.state !== 'weekend' && d.state !== 'holiday' && <span className="truncate rounded bg-sky-200 px-1 py-0.5 font-medium text-sky-900" title={d.leave.reason ?? ''}>Leave{d.leave.leave_type ? ` · ${d.leave.leave_type}` : ''}</span>}
                  {d.state === 'conflict' && <span className="font-semibold text-red-700">Leave clash</span>}
                  {d.holiday && <span className="truncate font-medium text-amber-800" title={d.holiday}>{d.holiday}</span>}
                  {d.state === 'tentative' && <span className="text-slate-600">On hold</span>}
                  {d.notes.length > 0 && <span className="truncate rounded bg-yellow-100 px-1 py-0.5 text-yellow-900 ring-1 ring-yellow-300" title={d.notes.map((n) => n.note).join('\n')}>📝 {d.notes.length > 1 ? `${d.notes.length} notes` : d.notes[0].note}</span>}
                </div>
              )
            })}
          </div>
        </div>
      )}
      <p className="mt-2 text-xs text-slate-500">Click a day to add notes or mark leave.</p>
      <div className="mt-2"><Legend /></div>
      <CalendarDayDialog day={data?.days.find((d) => d.date === picked) ?? null} leaveTypes={data?.leave_types ?? []} personal={data?.personal_leave ?? null}
        onClose={() => setPicked(null)} onChanged={reload} />
    </section>
  )
}
