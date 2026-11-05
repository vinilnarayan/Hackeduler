import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Boxes, CalendarClock, CheckCircle2, Clock, Download, Gauge, Plane, Server, Table2, UserCheck, XCircle } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { get, qs } from '../../api/client'
import type { AdminBooking, BookingStatus, Product } from '../../api/types'
import { AdminBookingModal } from '../../components/AdminBookingModal'
import { Empty, ErrorState, PageHeader, Spinner, StatCard, StatusBadge } from '../../components/ui'
import { fmt } from '../../lib/dates'
import { STATUS_CHART } from '../../lib/status'
import { useAsync } from '../../lib/useAsync'

const SERIES = '#2a78d6'
const AXIS = { fontSize: 11, fill: '#64748b' }

function ChartCard({ title, children, table }: { title: string; children: ReactNode; table: { cols: string[]; rows: (string | number)[][] } }) {
  const [showTable, setShowTable] = useState(false)
  return (
    <div className="card p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">{title}</h3>
        <button className="btn-ghost px-2 py-1 text-xs" aria-pressed={showTable} onClick={() => setShowTable(!showTable)}><Table2 className="h-3.5 w-3.5" />{showTable ? 'Chart' : 'Table'}</button>
      </div>
      {showTable ? (
        <div className="max-h-64 overflow-auto"><table className="min-w-full text-xs"><thead><tr>{table.cols.map((c) => <th key={c} className="th">{c}</th>)}</tr></thead>
          <tbody>{table.rows.map((r, i) => <tr key={i} className="border-t border-slate-100">{r.map((v, j) => <td key={j} className="td tabular-nums">{v}</td>)}</tr>)}</tbody></table></div>
      ) : <div className="h-64">{children}</div>}
    </div>
  )
}

const tip = { contentStyle: { fontSize: 12, borderRadius: 6, border: '1px solid #e2e8f0' }, cursor: { fill: 'rgba(148,163,184,0.15)' } }

export default function AdminDashboard() {
  const [range, setRange] = useState({ start: '', end: '', product_id: '' })
  const { data, error, loading, reload } = useAsync<any>(() => get('/api/admin/dashboard' + qs(range)), [range.start, range.end, range.product_id])
  const products = useAsync<Product[]>(() => get('/api/admin/products'))
  const [sel, setSel] = useState<string | null>(null)
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading && !data) return <Spinner />
  const k = data.kpis
  const ch = data.charts
  return (
    <div className="space-y-6">
      <PageHeader title="Admin Dashboard" subtitle={`Today: ${fmt(data.today, 'EEEE, dd MMM yyyy')} · Charts: ${fmt(data.range.start)} – ${fmt(data.range.end)}`}
        actions={<>
          <select className="input w-48 py-1" aria-label="Product" value={range.product_id} onChange={(e) => setRange({ ...range, product_id: e.target.value })}>
            <option value="">All products</option>{products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <label className="text-xs"><span className="sr-only">From</span><input type="date" className="input py-1" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} aria-label="Range start" /></label>
          <span className="text-slate-400">–</span>
          <label className="text-xs"><span className="sr-only">To</span><input type="date" className="input py-1" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} aria-label="Range end" /></label>
          <a className="btn-secondary" href={'/api/admin/reports/bookings.csv' + qs(range)}><Download className="h-4 w-4" />CSV</a>
          <a className="btn-secondary" href={'/api/admin/reports/bookings.xlsx' + qs(range)}><Download className="h-4 w-4" />Excel</a>
        </>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <StatCard label="Active resources" value={k.active_resources} hint={`${k.total_resources} total`} icon={<Server className="h-5 w-5" />} />
        <StatCard label="Available today" value={k.available_today} icon={<UserCheck className="h-5 w-5" />} tone="green" />
        <StatCard label="Occupied today" value={k.occupied_today} icon={<CalendarClock className="h-5 w-5" />} tone="red" />
        <StatCard label="Pending reservations today" value={k.reserved_today} icon={<Clock className="h-5 w-5" />} tone="blue" />
        <StatCard label="Engineers on leave" value={k.on_leave_today} icon={<Plane className="h-5 w-5" />} tone="slate" />
        <StatCard label="Utilisation (range)" value={`${k.utilization_pct}%`} icon={<Gauge className="h-5 w-5" />} tone="violet" />
        <Link to="/admin/bookings?status=pending_approval"><StatCard label="Pending requests" value={k.pending_requests} icon={<Clock className="h-5 w-5" />} tone="blue" /></Link>
        <StatCard label="Approved" value={k.approved} icon={<CheckCircle2 className="h-5 w-5" />} tone="green" />
        <StatCard label="Completed" value={k.completed} icon={<CheckCircle2 className="h-5 w-5" />} tone="violet" />
        <StatCard label="Rejected / cancelled" value={`${k.rejected} / ${k.cancelled}`} icon={<XCircle className="h-5 w-5" />} tone="red" />
        <StatCard label="Expired" value={k.expired} icon={<Clock className="h-5 w-5" />} tone="amber" />
        <StatCard label="Bookings in range" value={k.bookings_in_range} hint={`${k.bookings_without_resource} without a resource`} icon={<Boxes className="h-5 w-5" />} tone="blue" />
        <Link to="/admin/conflicts"><StatCard label="Unresolved conflicts" value={k.unresolved_conflicts} icon={<AlertTriangle className="h-5 w-5" />} tone={k.unresolved_conflicts ? 'red' : 'slate'} /></Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Monthly resource utilisation (%)" table={{ cols: ['Month', 'Booked days', 'Capacity days', 'Utilisation %'], rows: ch.monthly_utilization.map((m: any) => [m.month, m.used_days, m.capacity_days, m.utilization_pct]) }}>
          <ResponsiveContainer><BarChart data={ch.monthly_utilization} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#eef2f7" /><XAxis dataKey="month" tick={AXIS} tickLine={false} axisLine={{ stroke: '#cbd5e1' }} /><YAxis tick={AXIS} tickLine={false} axisLine={false} domain={[0, 100]} unit="%" />
            <Tooltip {...tip} formatter={(v: any, _n, p: any) => [`${v}% (${p.payload.used_days}/${p.payload.capacity_days} days)`, 'Utilisation']} />
            <Bar dataKey="utilization_pct" fill={SERIES} radius={[4, 4, 0, 0]} maxBarSize={28} />
          </BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Monthly booking volume (submitted)" table={{ cols: ['Month', 'Requests'], rows: ch.monthly_volume.map((m: any) => [m.month, m.count]) }}>
          <ResponsiveContainer><BarChart data={ch.monthly_volume} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#eef2f7" /><XAxis dataKey="month" tick={AXIS} tickLine={false} axisLine={{ stroke: '#cbd5e1' }} /><YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip {...tip} formatter={(v: any) => [v, 'Requests']} /><Bar dataKey="count" fill={SERIES} radius={[4, 4, 0, 0]} maxBarSize={28} />
          </BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Resource-wise allocation (booked working days)" table={{ cols: ['Resource', 'Engineer', 'Booked', 'Capacity', '%'], rows: ch.resource_allocation.map((r: any) => [r.resource, r.engineer_name, r.booked_days, r.capacity_days, r.utilization_pct]) }}>
          <ResponsiveContainer><BarChart layout="vertical" data={ch.resource_allocation.map((r: any) => ({ ...r, label: `${r.resource} · ${r.engineer_name}` }))} margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
            <CartesianGrid horizontal={false} stroke="#eef2f7" /><XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} /><YAxis type="category" dataKey="label" tick={AXIS} width={170} tickLine={false} axisLine={false} />
            <Tooltip {...tip} formatter={(v: any, _n, p: any) => [`${v} of ${p.payload.capacity_days} days (${p.payload.utilization_pct}%)`, 'Booked']} />
            <Bar dataKey="booked_days" fill={SERIES} radius={[0, 4, 4, 0]} maxBarSize={18} />
          </BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Booking status distribution (bookings in range)" table={{ cols: ['Status', 'Count'], rows: ch.status_distribution.map((s: any) => [s.label, s.count]) }}>
          <ResponsiveContainer><BarChart layout="vertical" data={ch.status_distribution} margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
            <CartesianGrid horizontal={false} stroke="#eef2f7" /><XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} /><YAxis type="category" dataKey="label" tick={AXIS} width={120} tickLine={false} axisLine={false} />
            <Tooltip {...tip} formatter={(v: any) => [v, 'Bookings']} />
            <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={18}>{ch.status_distribution.map((s: any) => <Cell key={s.status} fill={STATUS_CHART[s.status as BookingStatus]} />)}</Bar>
          </BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Bookings by product (in range)" table={{ cols: ['Product', 'Bookings', 'With resource', 'Without resource'], rows: ch.product_distribution.map((p: any) => [p.product, p.count, p.with_resource, p.without_resource]) }}>
          {ch.product_distribution.length === 0 ? <Empty title="No bookings in range" /> : (
            <ResponsiveContainer><BarChart layout="vertical" data={ch.product_distribution} margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid horizontal={false} stroke="#eef2f7" /><XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} /><YAxis type="category" dataKey="product" tick={AXIS} width={170} tickLine={false} axisLine={false} />
              <Tooltip {...tip} formatter={(v: any, _n, p: any) => [`${v} (${p.payload.with_resource} with resource, ${p.payload.without_resource} without)`, 'Bookings']} />
              <Bar dataKey="count" fill={SERIES} radius={[0, 4, 4, 0]} maxBarSize={18} />
            </BarChart></ResponsiveContainer>
          )}
        </ChartCard>
        <ChartCard title="Bookings by product and implementation" table={{ cols: ['Product', 'Implementation', 'Bookings'], rows: ch.implementation_distribution.map((i: any) => [i.product, i.implementation, i.count]) }}>
          {ch.implementation_distribution.length === 0 ? <Empty title="No bookings in range" /> : (
            <ResponsiveContainer><BarChart layout="vertical" data={ch.implementation_distribution.slice(0, 12).map((i: any) => ({ ...i, label: `${i.product} · ${i.implementation}` }))} margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid horizontal={false} stroke="#eef2f7" /><XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} /><YAxis type="category" dataKey="label" tick={AXIS} width={220} tickLine={false} axisLine={false} />
              <Tooltip {...tip} formatter={(v: any) => [v, 'Bookings']} /><Bar dataKey="count" fill={SERIES} radius={[0, 4, 4, 0]} maxBarSize={16} />
            </BarChart></ResponsiveContainer>
          )}
        </ChartCard>
        <div className="lg:col-span-2"><ProductMatrix m={ch.product_month_matrix} /></div>
        <div className="lg:col-span-2">
          <ChartCard title="Activity type distribution (active & completed bookings in range)" table={{ cols: ['Activity', 'Bookings'], rows: ch.activity_distribution.map((a: any) => [a.activity, a.count]) }}>
            {ch.activity_distribution.length === 0 ? <Empty title="No bookings in range" /> : (
              <ResponsiveContainer><BarChart layout="vertical" data={ch.activity_distribution} margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
                <CartesianGrid horizontal={false} stroke="#eef2f7" /><XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} /><YAxis type="category" dataKey="activity" tick={AXIS} width={260} tickLine={false} axisLine={false} />
                <Tooltip {...tip} formatter={(v: any) => [v, 'Bookings']} /><Bar dataKey="count" fill={SERIES} radius={[0, 4, 4, 0]} maxBarSize={16} />
              </BarChart></ResponsiveContainer>
            )}
          </ChartCard>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <BookingList title="Pending approval" items={data.pending_bookings} onOpen={setSel} empty="No pending requests" />
        <BookingList title="Upcoming approved bookings" items={data.upcoming_bookings} onOpen={setSel} empty="No upcoming bookings" />
        <div className="card">
          <div className="border-b border-slate-200 px-4 py-2 text-sm font-semibold">Upcoming holidays & leave today</div>
          <ul className="divide-y divide-slate-100 text-sm">
            {data.upcoming_holidays.map((h: any) => <li key={h.date} className="flex justify-between px-4 py-2"><span>{h.name}</span><span className="text-slate-500">{fmt(h.date)}</span></li>)}
            {data.engineers_on_leave_today.map((l: any) => <li key={l.resource} className="flex justify-between px-4 py-2"><span><Plane className="mr-1 inline h-3.5 w-3.5" />{l.engineer_name}</span><span className="text-slate-500">{l.resource} · on leave</span></li>)}
            {!data.upcoming_holidays.length && !data.engineers_on_leave_today.length && <li className="px-4 py-6 text-center text-slate-500">Nothing scheduled</li>}
          </ul>
        </div>
      </div>
      {sel && <AdminBookingModal bookingId={sel} onClose={() => setSel(null)} onChanged={reload} />}
    </div>
  )
}

/** Product x month matrix: counts with a single-hue sequential tint; numbers always shown for accessibility. */
function ProductMatrix({ m }: { m: { months: string[]; rows: { product: string; counts: number[]; total: number }[] } }) {
  const max = Math.max(1, ...m.rows.flatMap((r) => r.counts))
  const RAMP = ['#ffffff', '#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf']
  const shade = (v: number) => (v === 0 ? RAMP[0] : RAMP[Math.min(RAMP.length - 1, 1 + Math.floor(((v - 1) / max) * (RAMP.length - 1)))])
  const totals = m.months.map((_, i) => m.rows.reduce((a, r) => a + r.counts[i], 0))
  return (
    <div className="card p-4">
      <h3 className="mb-1 text-sm font-semibold">Monthly bookings by product</h3>
      <p className="mb-2 text-xs text-slate-500">Includes activities without a security resource; undated ones are counted in their submission month.</p>
      {m.rows.length === 0 ? <Empty title="No bookings in range" /> : (
        <div className="overflow-x-auto"><table className="min-w-full border-separate border-spacing-0.5 text-xs">
          <thead><tr><th className="th">Product</th>{m.months.map((mm) => <th key={mm} className="px-1 py-1 text-center font-medium text-slate-500">{mm.slice(2)}</th>)}<th className="th text-right">Total</th></tr></thead>
          <tbody>
            {m.rows.map((r) => (
              <tr key={r.product}><th scope="row" className="pr-3 text-left font-medium whitespace-nowrap">{r.product}</th>
                {r.counts.map((v, i) => <td key={i} title={`${r.product} · ${m.months[i]}: ${v}`} className={`min-w-9 rounded px-1 py-1.5 text-center tabular-nums ${v / max > 0.6 ? 'text-white' : 'text-slate-800'}`} style={{ background: shade(v) }}>{v || ''}</td>)}
                <td className="pl-2 text-right font-semibold tabular-nums">{r.total}</td></tr>
            ))}
            <tr className="border-t"><th scope="row" className="pt-1 pr-3 text-left text-slate-500">All</th>{totals.map((t, i) => <td key={i} className="pt-1 text-center font-medium text-slate-600 tabular-nums">{t || ''}</td>)}<td className="pt-1 pl-2 text-right font-semibold tabular-nums">{totals.reduce((a, b) => a + b, 0)}</td></tr>
          </tbody>
        </table></div>
      )}
    </div>
  )
}

function BookingList({ title, items, onOpen, empty }: { title: string; items: AdminBooking[]; onOpen: (id: string) => void; empty: string }) {
  return (
    <div className="card">
      <div className="border-b border-slate-200 px-4 py-2 text-sm font-semibold">{title}</div>
      {items.length === 0 ? <Empty title={empty} /> : (
        <ul className="divide-y divide-slate-100">{items.map((b) => (
          <li key={b.id}><button className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50" onClick={() => onOpen(b.id)}>
            <div className="min-w-0 flex-1"><div className="truncate font-medium">{b.application_name}</div><div className="truncate text-xs text-slate-500">{b.product_name ? `${b.product_name} · ` : ''}{b.requires_resource ? `${b.resource_display_name} · ${b.engineer_name} · ` : 'No resource · '}{b.start_date ? `${fmt(b.start_date, 'dd MMM')}–${fmt(b.end_date, 'dd MMM')}` : 'date open'}</div></div>
            <StatusBadge status={b.status} />
          </button></li>
        ))}</ul>
      )}
    </div>
  )
}
