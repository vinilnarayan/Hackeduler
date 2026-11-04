import { useMemo, useState } from 'react'
import { format, isToday, isWeekend } from 'date-fns'
import { AlertTriangle, CalendarDays, ChevronLeft, ChevronRight, Filter } from 'lucide-react'
import { get, qs } from '../api/client'
import type { ActivityType, BookingStatus, CalendarCell, CalendarGrid, CalendarResource } from '../api/types'
import { iso, parse, rangeTitle, shift, viewRange, type View } from '../lib/dates'
import { CELL_STYLE, STATUS_LABELS, cellExplanation } from '../lib/status'
import { useAsync } from '../lib/useAsync'
import { ErrorState, Spinner } from './ui'

export function Legend({ compact, showMine = true }: { compact?: boolean; showMine?: boolean }) {
  const order = ['available', 'limited', 'reserved', 'occupied', 'non_working', 'inactive'] as const
  return (
    <div className={`flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-600 ${compact ? '' : 'card px-3 py-2'}`} aria-label="Availability colour legend">
      {order.map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          <span className={`inline-block h-3 w-3 rounded-sm ${CELL_STYLE[s].cls}`} aria-hidden />
          <span><span className="font-medium">{CELL_STYLE[s].label}</span> – {CELL_STYLE[s].meaning}</span>
        </span>
      ))}
      {showMine && <span className="inline-flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-sm bg-emerald-500 ring-2 ring-offset-1 ring-slate-900" aria-hidden /> Your booking</span>}
    </div>
  )
}

interface Props {
  mode: 'requester' | 'admin'
  activityTypes?: ActivityType[]
  onCellClick?: (r: CalendarResource, c: CalendarCell) => void
  refreshKey?: number
  initialView?: View
}

export function ResourceCalendar({ mode, activityTypes = [], onCellClick, refreshKey = 0, initialView = 'month' }: Props) {
  const [view, setView] = useState<View>(initialView)
  const [anchor, setAnchor] = useState(new Date())
  const [activityId, setActivityId] = useState('')
  const [statusFilter, setStatusFilter] = useState<'' | BookingStatus>('')
  const [onlyAvailable, setOnlyAvailable] = useState(false)
  const [s, e] = viewRange(anchor, view)
  const url = (mode === 'admin' ? '/api/admin/calendar' : '/api/calendar') + qs({ start: iso(s), end: iso(e), activity_type_id: activityId })
  const { data, error, loading, reload } = useAsync<CalendarGrid>(() => get(url), [url, refreshKey])

  const resources = useMemo(() => {
    let rs = data?.resources ?? []
    if (onlyAvailable) rs = rs.filter((r) => r.days.some((d) => d.state === 'available'))
    return rs
  }, [data, onlyAvailable])
  const days = data?.resources[0]?.days.map((d) => d.date) ?? []
  const holidays = new Map((data?.holidays ?? []).map((h) => [h.date, h.name]))

  const visibleCell = (c: CalendarCell): CalendarCell => {
    if (!statusFilter || !c.bookings) return c
    const b = c.bookings.filter((x) => x.status === statusFilter)
    if (b.length) return { ...c, bookings: b }
    if (c.state === 'occupied' || c.state === 'reserved') return { ...c, bookings: [], state: c.state, dim: true } as any
    return c
  }

  const clickable = (c: CalendarCell) =>
    !!onCellClick && (mode === 'admin' ? true : c.state === 'available' || c.state === 'limited' || !!c.mine)

  const cellTitle = (r: CalendarResource, c: CalendarCell) => {
    const parts = [`${r.display_name}${r.engineer_name ? ` (${r.engineer_name})` : ''}`, format(parse(c.date), 'EEE dd MMM yyyy'), cellExplanation(c.state, c.reason, c.label)]
    if (c.mine) parts.push('Your booking')
    c.bookings?.forEach((b) => parts.push(`${b.application_name} – ${STATUS_LABELS[b.status]}${b.forced ? ' (FORCED)' : ''}`))
    if (c.conflict) parts.push('⚠ Overlapping allocations')
    return parts.join(' · ')
  }

  return (
    <div className="space-y-3">
      <div className="card flex flex-wrap items-center gap-2 p-2">
        <div className="flex items-center gap-1">
          <button className="btn-secondary px-2" aria-label="Previous period" onClick={() => setAnchor(shift(anchor, view, -1))}><ChevronLeft className="h-4 w-4" /></button>
          <button className="btn-secondary" onClick={() => setAnchor(new Date())}>Today</button>
          <button className="btn-secondary px-2" aria-label="Next period" onClick={() => setAnchor(shift(anchor, view, 1))}><ChevronRight className="h-4 w-4" /></button>
        </div>
        <div className="min-w-48 px-2 text-sm font-semibold">{rangeTitle(anchor, view)}</div>
        <label className="flex items-center gap-1 text-sm">
          <CalendarDays className="h-4 w-4 text-slate-500" aria-hidden />
          <span className="sr-only">Go to date</span>
          <input type="date" className="input w-36 py-1" value={iso(anchor)} onChange={(ev) => ev.target.value && setAnchor(parse(ev.target.value))} />
        </label>
        <div className="ml-auto flex rounded-md border border-slate-300 bg-white p-0.5" role="tablist" aria-label="Calendar view">
          {(['month', 'week', 'day'] as View[]).map((v) => (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
              className={`rounded px-3 py-1 text-sm capitalize ${view === v ? 'bg-blue-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`}>{v}</button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 text-sm">
        <Filter className="mb-2 h-4 w-4 text-slate-400" aria-hidden />
        <label className="flex flex-col"><span className="label">Activity type (fit check)</span>
          <select className="input w-72" value={activityId} onChange={(ev) => setActivityId(ev.target.value)}>
            <option value="">— Any —</option>
            {activityTypes.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.base_duration_days}d){a.description ? ` – ${a.description}` : ''}</option>)}
          </select>
        </label>
        {mode === 'admin' && (
          <label className="flex flex-col"><span className="label">Booking status</span>
            <select className="input w-44" value={statusFilter} onChange={(ev) => setStatusFilter(ev.target.value as any)}>
              <option value="">All</option>
              <option value="pending_approval">Pending Approval</option>
              <option value="approved">Approved</option>
              <option value="completed">Completed</option>
            </select>
          </label>
        )}
        <label className="mb-2 flex items-center gap-2"><input type="checkbox" checked={onlyAvailable} onChange={(ev) => setOnlyAvailable(ev.target.checked)} /> Only resources with availability</label>
        {mode === 'admin' && !!data?.open_conflicts && (
          <span className="mb-1.5 inline-flex items-center gap-1 rounded bg-red-100 px-2 py-1 text-xs font-medium text-red-800"><AlertTriangle className="h-3.5 w-3.5" /> {data.open_conflicts} open conflict(s)</span>
        )}
      </div>

      <Legend showMine={mode === 'requester'} />

      {error ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <Spinner /> : (
        <div className="card overflow-x-auto">
          {view === 'day' ? (
            <DayList resources={resources} mode={mode} onClick={onCellClick} clickable={clickable} visibleCell={visibleCell} />
          ) : (
            <table className="min-w-full border-separate border-spacing-0 text-xs" aria-label="Resource availability calendar">
              <thead>
                <tr>
                  <th scope="col" className="sticky left-0 z-10 min-w-40 border-b border-slate-200 bg-white px-3 py-2 text-left font-semibold text-slate-600">Resource</th>
                  {days.map((d) => {
                    const dt = parse(d)
                    return (
                      <th key={d} scope="col" title={holidays.get(d) ?? ''}
                        className={`border-b border-slate-200 px-0.5 py-1 text-center font-medium ${isWeekend(dt) ? 'text-slate-400' : 'text-slate-600'} ${isToday(dt) ? 'bg-blue-50' : ''}`}>
                        <div className="text-[10px] uppercase">{format(dt, view === 'week' ? 'EEE' : 'EEEEE')}</div>
                        <div className={`${isToday(dt) ? 'mx-auto w-5 rounded-full bg-blue-700 text-white' : ''}`}>{format(dt, 'd')}</div>
                        {holidays.has(d) && <div className="mx-auto mt-0.5 h-1 w-1 rounded-full bg-slate-500" aria-label={`Holiday: ${holidays.get(d)}`} />}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {resources.map((r) => (
                  <tr key={r.id} className="group">
                    <th scope="row" className="sticky left-0 z-10 border-b border-slate-100 bg-white px-3 py-1 text-left font-normal group-hover:bg-slate-50">
                      <div className="font-semibold text-slate-800">{r.display_name}</div>
                      {r.engineer_name && <div className="text-[11px] text-slate-500">{r.engineer_name}</div>}
                      {!r.is_active && <div className="text-[10px] font-medium text-slate-400 uppercase">Inactive</div>}
                      {r.is_active && r.inactive_from && <div className="text-[10px] font-medium text-amber-700">Inactive from {format(parse(r.inactive_from), 'dd MMM yyyy')}</div>}
                    </th>
                    {r.days.map((raw) => {
                      const c = visibleCell(raw)
                      const can = clickable(c)
                      const style = CELL_STYLE[c.state]
                      const dim = (c as any).dim
                      const Tag = can ? 'button' : 'div'
                      return (
                        <td key={c.date} className={`border-b border-slate-100 p-0.5 ${isToday(parse(c.date)) ? 'bg-blue-50/60' : ''}`}>
                          <Tag
                            {...(can ? { type: 'button', onClick: () => onCellClick!(r, raw) } : {})}
                            title={cellTitle(r, c)} aria-label={cellTitle(r, c)}
                            className={`relative block w-full rounded-sm text-left text-[10px] leading-tight text-white ${view === 'week' ? 'h-14 px-1 py-0.5' : 'h-8 min-w-6'} ${style.cls} ${dim ? 'opacity-30' : ''} ${c.mine ? 'ring-2 ring-slate-900 ring-offset-1' : ''} ${can ? 'cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-700' : 'cursor-default'}`}>
                            {view === 'week' && (
                              <span className="line-clamp-3 font-medium drop-shadow-sm">
                                {c.bookings?.length ? c.bookings.map((b) => b.application_name).join(', ')
                                  : c.state === 'non_working' ? <span className="text-slate-700">{cellExplanation(c.state, c.reason, c.label)}</span>
                                  : c.state === 'inactive' ? '' : style.meaning.split(' ')[0]}
                              </span>
                            )}
                            {c.conflict && <AlertTriangle className="absolute top-0.5 right-0.5 h-3 w-3 text-yellow-200" aria-hidden />}
                            {c.bookings?.some((b) => b.forced) && <span className="absolute bottom-0 left-0.5 text-[8px] font-bold">F</span>}
                          </Tag>
                        </td>
                      )
                    })}
                  </tr>
                ))}
                {resources.length === 0 && (
                  <tr><td colSpan={days.length + 1} className="p-8 text-center text-sm text-slate-500">No resources match the current filters.</td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function DayList({ resources, mode, onClick, clickable, visibleCell }: {
  resources: CalendarResource[]; mode: 'requester' | 'admin'; onClick?: (r: CalendarResource, c: CalendarCell) => void
  clickable: (c: CalendarCell) => boolean; visibleCell: (c: CalendarCell) => CalendarCell
}) {
  if (!resources.length) return <div className="p-8 text-center text-sm text-slate-500">No resources match the current filters.</div>
  return (
    <ul className="divide-y divide-slate-100">
      {resources.map((r) => {
        const c = visibleCell(r.days[0])
        const can = clickable(c)
        return (
          <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <span className={`h-8 w-2 rounded ${CELL_STYLE[c.state].cls}`} aria-hidden />
            <div className="w-44">
              <div className="font-semibold">{r.display_name}</div>
              {mode === 'admin' && <div className="text-xs text-slate-500">{r.engineer_name}</div>}
            </div>
            <div className="flex-1 text-sm">
              <div className="font-medium">{cellExplanation(c.state, c.reason, c.label)}{c.mine ? ' · Your booking' : ''}</div>
              {c.bookings?.map((b) => <div key={b.id} className="text-xs text-slate-600">{b.application_name} — {STATUS_LABELS[b.status]}{b.activity ? ` · ${b.activity}` : ''}{b.forced ? ' · FORCED' : ''}</div>)}
              {c.conflict && <div className="text-xs font-medium text-red-700">⚠ Overlapping allocations – review required</div>}
            </div>
            {can && <button className="btn-secondary" onClick={() => onClick!(r, r.days[0])}>{mode === 'admin' ? 'Open' : c.mine ? 'View' : 'Book this resource'}</button>}
          </li>
        )
      })}
    </ul>
  )
}
