import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react'
import { get } from '../../api/client'
import { shiftMonth } from '../../components/MyMonthCalendar'
import { ErrorState, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { distinctColours } from '../../lib/colours'
import { fmt, initials } from '../../lib/dates'
import { useAsync } from '../../lib/useAsync'

interface Entry { booking_id: string; resource_id: string; resource_name: string; engineer_name: string; application_name: string; application_version: string; activity_name: string; status: string; tentative: boolean; start_date: string | null; end_date: string | null }
interface LeaveE { leave_id: string; resource_id: string; resource_name: string; engineer_name: string; leave_type: string | null }
interface FreeE { resource_id: string; resource_name: string; engineer_name: string }
interface Day { date: string; in_month: boolean; weekend: boolean; holiday: string | null; entries: Entry[]; leaves: LeaveE[]; free: FreeE[] }
interface Res { id: string; display_name: string; engineer_name: string; is_active: boolean }
interface Cal { month: string; week?: string | null; today: string; days: Day[]; resources: Res[]; summary: { working_days: number; booked_days: number; leave_days: number; holidays: number } }

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MAX_SHOWN = 4
const monthLabel = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const statusLabel = (s: string) => s.replace(/_/g, ' ')
/** The engineer's name is what people recognise; the resource name is only a fallback. */
const who = (x: { engineer_name?: string | null; resource_name: string }) => x.engineer_name || x.resource_name
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const shiftDays = (iso: string, n: number) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const weekTitle = (days: Day[]) => days.length ? `${fmt(days[0].date, 'd MMM')} – ${fmt(days[days.length - 1].date, 'd MMM yyyy')}` : 'Week'

/** `mode="lead"`: the read-only copy for team leads (resource users): own API, and no links into the admin pages. */
export default function TeamCalendar({ mode = 'admin' }: { mode?: 'admin' | 'lead' }) {
  const api = mode === 'lead' ? '/api/resource/team-calendar' : '/api/admin/team-calendar'
  const [view, setView] = useState<'month' | 'week'>('month')
  const [layout, setLayout] = useState<'day' | 'resource'>('day')
  const [month, setMonth] = useState<string | undefined>(undefined)
  const [anchor, setAnchor] = useState<string>(() => isoDay(new Date()))
  const [resource, setResource] = useState('')
  const [picked, setPicked] = useState<string | null>(null)
  const isWeek = view === 'week'
  const { data, error, loading, reload } = useAsync<Cal>(
    () => get(api + (isWeek || month || resource ? '?' + [isWeek ? `week=${anchor}` : month && `month=${month}`, resource && `resource_id=${resource}`].filter(Boolean).join('&') : '')), [isWeek, month, anchor, resource])
  if (error) return <ErrorState message={error} onRetry={reload} />
  const cur = data?.month ?? month
  const stale = !!data && (isWeek ? !data.week : !!data.week)    // the other view's data while the new one loads
  // Every booking in the view gets its own colour (never repeated within it), in start-date order.
  const bookingColours = useMemo(() => {
    const seen = new Map<string, string>()
    for (const d of data?.days ?? []) for (const e of d.entries) { const st = e.start_date ?? ''; if (!seen.has(e.booking_id) || st < seen.get(e.booking_id)!) seen.set(e.booking_id, st) }
    return distinctColours([...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]) || a[0].localeCompare(b[0])).map(([id]) => id))
  }, [data])
  const day = data?.days.find((d) => d.date === picked) ?? null
  const s = data?.summary
  const step = (n: number) => (isWeek ? setAnchor((a) => shiftDays(a, 7 * n)) : cur && setMonth(shiftMonth(cur, n)))
  const goToday = () => { setMonth(undefined); setAnchor(isoDay(new Date())) }
  const title = isWeek ? weekTitle(stale ? [] : data?.days ?? []) : cur ? monthLabel(cur) : 'Calendar'
  const unit = isWeek ? 'week' : 'month'
  const dayLabel = (d: Day) => `${d.date}: ${d.entries.length} activities, ${d.leaves.length} on leave${d.holiday ? `, ${d.holiday}` : ''}`
  const dayClass = (d: Day) => d.holiday ? 'bg-amber-50 ring-amber-300' : d.weekend ? 'bg-slate-100 ring-slate-200' : 'bg-white ring-slate-200'
  const open = (date: string) => ({ onClick: () => setPicked(date), onKeyDown: (e: React.KeyboardEvent) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setPicked(date) } } })
  const entryTitle = (e: Entry) => `${who(e)} (${e.resource_name}) - ${e.application_name} v${e.application_version} - ${e.activity_name} [${statusLabel(e.status)}]`
  const leaveBox = (l: LeaveE, date: string) => <span key={l.leave_id + date} className="truncate rounded bg-sky-200 px-1 py-0.5 font-medium text-sky-900" title={`${who(l)} (${l.resource_name}) on leave`}><b>{initials(l.engineer_name, l.resource_name.replace(/^Resource /, 'R'))}</b> leave</span>
  const seg = (on: boolean) => `rounded px-3 py-1 text-sm ${on ? 'bg-blue-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`
  return (
    <div>
      <PageHeader title="Team Calendar" subtitle="Every engineer's activity, leave and the holidays, by month or by week. Click a day for the details." />
      <section className="card p-4" aria-label="Team calendar">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-2 text-base font-semibold">{title}</h2>
          <button className="btn-secondary" aria-label={`Previous ${unit}`} disabled={!data} onClick={() => step(-1)}><ChevronLeft className="h-4 w-4" /></button>
          <button className="btn-secondary" aria-label={`Next ${unit}`} disabled={!data} onClick={() => step(1)}><ChevronRight className="h-4 w-4" /></button>
          <button className="btn-secondary" onClick={goToday}>Today</button>
          <div className="flex rounded-md border border-slate-300 bg-white p-0.5" role="group" aria-label="View">
            <button aria-pressed={!isWeek} className={seg(!isWeek)} onClick={() => { if (isWeek) { setView('month'); setMonth(data?.days[0]?.date.slice(0, 7)) } }}>Month</button>
            <button aria-pressed={isWeek} className={seg(isWeek)} onClick={() => { if (!isWeek) { setView('week'); setAnchor(month && month !== isoDay(new Date()).slice(0, 7) ? `${month}-01` : isoDay(new Date())) } }}>Week</button>
          </div>
          <div className="flex rounded-md border border-slate-300 bg-white p-0.5" role="group" aria-label="Layout">
            <button aria-pressed={layout === 'day'} className={seg(layout === 'day')} onClick={() => setLayout('day')}>By day</button>
            <button aria-pressed={layout === 'resource'} className={seg(layout === 'resource')} onClick={() => setLayout('resource')}>By engineer</button>
          </div>
          <label className="ml-auto flex items-center gap-2 text-sm"><span>Engineer</span>
            <select className="input w-52" aria-label="Engineer" value={resource} onChange={(e) => setResource(e.target.value)}>
              <option value="">All engineers</option>
              {data?.resources.map((r) => <option key={r.id} value={r.id}>{r.engineer_name || r.display_name}</option>)}
            </select>
          </label>
        </div>
        {s && !stale && <div className="mb-3 flex flex-wrap gap-1.5 text-xs">
          <span className="rounded-full bg-blue-100 px-2 py-0.5 font-medium text-blue-900">Activity days {s.booked_days}</span>
          <span className="rounded-full bg-sky-100 px-2 py-0.5 font-medium text-sky-900">Leave days {s.leave_days}</span>
          <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-900">Holidays {s.holidays}</span>
        </div>}
        {(loading && !data) || stale ? <Spinner /> : data && !isWeek && layout === 'day' && (
          <div className="overflow-x-auto">
            <div role="grid" aria-label={monthLabel(data.month)} className="grid min-w-[860px] grid-cols-7 gap-1">
              {WEEKDAYS.map((w) => <div key={w} role="columnheader" className="px-1 pb-1 text-center text-xs font-medium text-slate-500">{w}</div>)}
              {data.days.map((d) => {
                const shown = d.entries.slice(0, MAX_SHOWN)
                const more = d.entries.length - shown.length
                const isToday = d.date === data.today
                return (
                  <div key={d.date} role="gridcell" tabIndex={0} data-date={d.date} aria-label={dayLabel(d)} {...open(d.date)}
                    className={`flex min-h-28 cursor-pointer flex-col gap-0.5 rounded-md p-1.5 text-[11px] ring-1 hover:brightness-95 ${dayClass(d)}${d.in_month ? '' : ' opacity-40'}${isToday ? ' outline outline-2 outline-offset-1 outline-blue-600' : ''}`}>
                    <div className={`text-xs font-semibold ${isToday ? 'text-blue-700' : ''}`}>{Number(d.date.slice(8))}</div>
                    {d.holiday && <span className="truncate font-medium text-amber-800" title={d.holiday}>{d.holiday}</span>}
                    {shown.map((e) => (
                      <span key={e.booking_id + e.resource_id} title={entryTitle(e)}
                        style={bookingColours.get(e.booking_id)} className={`truncate rounded px-1 py-0.5${e.tentative ? ' border border-dashed border-slate-500' : ''}`}>
                        <b>{initials(e.engineer_name, e.resource_name.replace(/^Resource /, 'R'))}</b> {e.application_name}{e.application_version ? ` v${e.application_version}` : ''}
                      </span>
                    ))}
                    {more > 0 && <span className="font-medium text-slate-600">+{more} more</span>}
                    {d.leaves.map((l) => leaveBox(l, d.date))}
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {data && !stale && !isWeek && layout === 'resource' && (
          <MonthByEngineer data={data} resourceId={resource} colours={bookingColours} entryTitle={entryTitle} onPick={setPicked} />
        )}
        {data && !stale && isWeek && layout === 'day' && (
          <div className="overflow-x-auto">
            <div role="grid" aria-label={weekTitle(data.days)} className="grid min-w-[860px] grid-cols-7 gap-1">
              {data.days.map((d) => {
                const isToday = d.date === data.today
                return (
                  <div key={d.date} role="gridcell" tabIndex={0} data-date={d.date} aria-label={dayLabel(d)} {...open(d.date)}
                    className={`flex min-h-96 cursor-pointer flex-col gap-1.5 rounded-md p-2 text-xs ring-1 hover:brightness-95 ${dayClass(d)}${isToday ? ' outline outline-2 outline-offset-1 outline-blue-600' : ''}`}>
                    <div className="flex items-baseline justify-between"><span className={`text-lg font-bold ${isToday ? 'text-blue-700' : ''}`}>{Number(d.date.slice(8))}</span><span className="text-[11px] font-semibold text-slate-500">{fmt(d.date, 'EEE MMM')}</span></div>
                    {d.holiday && <span className="font-medium text-amber-800">{d.holiday}</span>}
                    {d.entries.map((e) => (
                      <div key={e.booking_id + e.resource_id} title={entryTitle(e)} style={bookingColours.get(e.booking_id)} className={`rounded px-2 py-1.5 leading-snug${e.tentative ? ' border border-dashed border-slate-500' : ''}`}>
                        <b>{initials(e.engineer_name, e.resource_name.replace(/^Resource /, 'R'))}</b> {e.application_name}{e.application_version ? ` v${e.application_version}` : ''}
                        <div className="text-[11px] opacity-80">{e.activity_name} · {who(e)}</div>
                      </div>
                    ))}
                    {d.leaves.map((l) => <div key={l.leave_id + d.date} className="rounded bg-sky-200 px-2 py-1.5 font-medium text-sky-900"><b>{initials(l.engineer_name, l.resource_name.replace(/^Resource /, 'R'))}</b> {who(l)} on leave</div>)}
                    {!d.entries.length && !d.leaves.length && !d.holiday && !d.weekend && <span className="text-[11px] text-slate-400 italic">Nothing booked</span>}
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {data && !stale && isWeek && layout === 'resource' && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] table-fixed border-separate border-spacing-1" aria-label={weekTitle(data.days)}>
              <thead><tr><th className="w-40" />{data.days.map((d) => <th key={d.date} className={`text-xs font-semibold ${d.date === data.today ? 'text-blue-700' : 'text-slate-500'}`}>{fmt(d.date, 'EEE d')}</th>)}</tr></thead>
              <tbody>
                {data.resources.filter((r) => !resource || r.id === resource).map((r) => (
                  <tr key={r.id}>
                    <th scope="row" className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-left text-xs font-semibold" title={r.display_name}>{r.engineer_name || r.display_name}</th>
                    {data.days.map((d) => {
                      const en = d.entries.filter((e) => e.resource_id === r.id)
                      const lv = d.leaves.filter((l) => l.resource_id === r.id)
                      const free = d.free.some((f) => f.resource_id === r.id)
                      return (
                        <td key={d.date} data-date={d.date} tabIndex={0} aria-label={`${r.engineer_name || r.display_name} ${d.date}`} {...open(d.date)}
                          className={`h-14 cursor-pointer rounded-md p-1 align-top text-[11px] ring-1 hover:brightness-95 ${dayClass(d)}`}>
                          {en.map((e) => <span key={e.booking_id} title={entryTitle(e)} style={bookingColours.get(e.booking_id)} className={`mb-0.5 block truncate rounded px-1 py-0.5${e.tentative ? ' border border-dashed border-slate-500' : ''}`}>{e.application_name}{e.application_version ? ` v${e.application_version}` : ''}</span>)}
                          {lv.map((l) => <span key={l.leave_id} className="mb-0.5 block truncate rounded bg-sky-200 px-1 py-0.5 font-semibold text-sky-900">Leave</span>)}
                          {free && <span className="text-slate-400 italic">Free</span>}
                          {d.holiday && !en.length && <span className="text-amber-800">{d.holiday}</span>}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
          <span><span className="mr-1 inline-block h-3 w-3 rounded-sm" style={{ background: 'linear-gradient(90deg,#cfe3ff,#ffd9c9,#d6f5d6)' }} />Activity (each booking has its own colour)</span>
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
                    <span style={bookingColours.get(e.booking_id)} className="rounded px-1.5 py-0.5 text-xs font-semibold">{who(e)}</span>
                    {mode === 'lead' ? <span className="font-medium">{e.application_name} v{e.application_version}</span> : (
                      <Link to={`/admin/bookings?booking=${encodeURIComponent(e.booking_id)}`} title="Open booking details"
                        className="inline-flex items-center gap-1 font-medium text-blue-700 hover:underline focus-visible:underline">
                        {e.application_name} v{e.application_version}<ExternalLink size={12} aria-hidden="true" /></Link>)}
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
                  {day.free.map((f) => <li key={f.resource_id} className="flex flex-wrap items-center gap-x-3 px-3 py-2"><span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-300">{who(f)}</span><span className="text-emerald-700">Free</span></li>)}
                </ul>
              )}
          </section>
          <section aria-label="Leave">
            <h3 className="mb-1 font-semibold">On leave</h3>
            {day.leaves.length === 0 ? <p className="text-slate-500">Nobody is on leave.</p> : (
              <ul className="divide-y divide-slate-100 rounded border border-slate-200">
                {day.leaves.map((l) => <li key={l.leave_id} className="flex flex-wrap items-center gap-x-3 px-3 py-2"><span className="font-medium">{who(l)}</span><span>{l.leave_type ?? 'Leave'}</span></li>)}
              </ul>
            )}
          </section>
        </div>}
      </Modal>
    </div>
  )
}

/** Month, one row per engineer: each booking is one bar across its days (weekends in between stay inside the bar). */
function MonthByEngineer({ data, resourceId, colours, entryTitle, onPick }: { data: Cal; resourceId: string; colours: Map<string, React.CSSProperties>; entryTitle: (e: Entry) => string; onPick: (date: string) => void }) {
  const days = data.days.filter((d) => d.in_month)
  const rows = data.resources.filter((r) => !resourceId || r.id === resourceId)
  type Run = { from: number; to: number; kind: 'booking' | 'leave' | 'empty'; entry?: Entry }
  const runsFor = (rid: string): Run[] => {
    const book = days.map((d) => d.entries.find((e) => e.resource_id === rid))
    const leave = days.map((d) => d.leaves.some((l) => l.resource_id === rid))
    const out: Run[] = []
    let i = 0
    while (i < days.length) {
      const e = book[i]
      if (e) {
        let j = i
        for (;;) {
          if (j + 1 >= days.length) break
          if (book[j + 1]?.booking_id === e.booking_id) { j++; continue }
          if (days[j + 1].weekend && !book[j + 1] && !leave[j + 1]) {     // weekend gap: stay in the bar if the same booking resumes after it
            let k = j + 1
            while (k < days.length && days[k].weekend && !book[k] && !leave[k]) k++
            if (k < days.length && book[k]?.booking_id === e.booking_id) { j = k; continue }
          }
          break
        }
        out.push({ from: i, to: j, kind: 'booking', entry: e }); i = j + 1
      } else if (leave[i]) {
        let j = i
        while (j + 1 < days.length && leave[j + 1] && !book[j + 1]) j++
        out.push({ from: i, to: j, kind: 'leave' }); i = j + 1
      } else { out.push({ from: i, to: i, kind: 'empty' }); i++ }
    }
    return out
  }
  const pick = (ev: React.MouseEvent<HTMLElement>, run: Run) => {   // a bar spans several days: open the day that was clicked
    const r = ev.currentTarget.getBoundingClientRect()
    const span = run.to - run.from + 1
    const idx = r.width > 0 ? Math.min(span - 1, Math.max(0, Math.floor(((ev.clientX - r.left) / r.width) * span))) : 0
    onPick(days[run.from + idx].date)
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-max border-separate border-spacing-0 text-[11px]" aria-label={monthLabel(data.month)}>
        <thead>
          <tr>
            <th className="sticky left-0 z-10 w-32 min-w-32 border-r-2 border-slate-200 bg-white" />
            {days.map((d) => (
              <th key={d.date} className={`h-9 min-w-[34px] border-b border-l border-slate-200 pt-0.5 text-center text-[11px] leading-tight font-bold ${d.weekend ? 'bg-slate-100' : ''} ${d.date === data.today ? 'text-blue-700' : ''}`}>
                {Number(d.date.slice(8))}<span className="block text-[9px] font-medium text-slate-500">{fmt(d.date, 'EEEEE')}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <th scope="row" className="sticky left-0 z-10 h-10 w-32 min-w-32 border-r-2 border-b border-slate-200 bg-white px-2 text-left text-xs font-semibold whitespace-nowrap" title={r.display_name}>{r.engineer_name || r.display_name}</th>
              {runsFor(r.id).map((run) => {
                const d = days[run.from]
                const base = 'h-10 cursor-pointer border-b border-l border-slate-200 align-middle hover:brightness-95'
                if (run.kind === 'empty') return <td key={d.date} data-date={d.date} tabIndex={0} aria-label={`${r.engineer_name || r.display_name} ${d.date}`} onClick={() => onPick(d.date)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(d.date) } }}
                  className={`${base} ${d.holiday ? 'bg-amber-50' : d.weekend ? 'bg-slate-100' : d.date === data.today ? 'bg-blue-50' : ''}`} title={d.holiday ?? undefined} />
                const e = run.entry
                return (
                  <td key={d.date} colSpan={run.to - run.from + 1} data-date={d.date} tabIndex={0} aria-label={`${r.engineer_name || r.display_name} ${d.date}`} onClick={(ev) => pick(ev, run)}
                    onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onPick(d.date) } }} className={`${base} py-0.5`}>
                    {e ? <span title={entryTitle(e)} style={colours.get(e.booking_id)} className={`mx-0.5 block truncate rounded px-1.5 py-1 font-semibold${e.tentative ? ' border border-dashed border-slate-500' : ''}`}>{e.application_name}{e.application_version ? ` v${e.application_version}` : ''}</span>
                      : <span className="mx-0.5 block truncate rounded bg-sky-200 px-1.5 py-1 font-semibold text-sky-900">Leave</span>}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-500">Scroll sideways to see the whole month. A booking is one bar across its days; click any cell for the day&apos;s details.</p>
    </div>
  )
}
