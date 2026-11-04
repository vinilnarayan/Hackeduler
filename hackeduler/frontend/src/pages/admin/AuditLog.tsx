import { Fragment, useState } from 'react'
import { Lock } from 'lucide-react'
import { get, qs } from '../../api/client'
import type { AuditEntry } from '../../api/types'
import { AuditChanges } from '../../components/AdminBookingModal'
import { Empty, ErrorState, PageHeader, Pill, Spinner } from '../../components/ui'
import { fmtDateTime } from '../../lib/dates'
import { useAsync } from '../../lib/useAsync'

export default function AuditLog() {
  const [f, setF] = useState({ booking_id: '', actor: '', action: '', start: '', end: '' })
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const PAGE = 100
  const validBid = !f.booking_id || /^[0-9a-f-]{36}$/i.test(f.booking_id)
  const { data, error, loading, reload } = useAsync<{ total: number; items: AuditEntry[] }>(
    () => get('/api/admin/audit' + qs({ ...f, booking_id: validBid ? f.booking_id : '', limit: PAGE, offset: page * PAGE })), [JSON.stringify(f), page])
  const s = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => { setPage(0); setF({ ...f, [k]: e.target.value }) }
  return (
    <div>
      <PageHeader title="Audit Log" subtitle="Append-only record of every booking and administrative action. Entries cannot be edited or deleted (enforced by database triggers)." actions={<Pill className="bg-slate-800 text-white"><Lock className="h-3 w-3" />Immutable</Pill>} />
      <div className="card mb-3 grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-5">
        <input className="input" placeholder="Booking ID (UUID)" aria-label="Booking ID" value={f.booking_id} onChange={s('booking_id')} />
        <input className="input" placeholder="Actor email" aria-label="Actor" value={f.actor} onChange={s('actor')} />
        <input className="input" placeholder="Action (e.g. force, approved)" aria-label="Action" value={f.action} onChange={s('action')} />
        <input type="date" className="input" aria-label="From" value={f.start} onChange={s('start')} />
        <input type="date" className="input" aria-label="To" value={f.end} onChange={s('end')} />
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? <Empty title="No audit events match" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Timestamp</th><th className="th">Action</th><th className="th">Actor</th><th className="th">Entity / Booking</th><th className="th">Reason</th><th className="th">Request ID</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.items.map((a) => (
              <Fragment key={a.id}>
                <tr className="cursor-pointer hover:bg-slate-50" tabIndex={0} onClick={() => setOpen(open === a.id ? null : a.id)} onKeyDown={(e) => e.key === 'Enter' && setOpen(open === a.id ? null : a.id)}>
                  <td className="td text-xs whitespace-nowrap">{fmtDateTime(a.created_at)}</td>
                  <td className="td"><Pill className={a.action.includes('force') || a.action.includes('denied') ? 'bg-red-100 text-red-800' : a.action.includes('failed') ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'}>{a.action}</Pill></td>
                  <td className="td text-xs">{a.actor_email}<div className="text-slate-500">{a.actor_role}{a.ip_address ? ` · ${a.ip_address}` : ''}</div></td>
                  <td className="td text-xs">{a.entity_type}{a.booking_id && <div className="font-mono text-slate-500">{a.booking_id}</div>}</td>
                  <td className="td max-w-xs text-xs">{a.reason}</td>
                  <td className="td font-mono text-[11px] text-slate-500">{a.request_id?.slice(0, 13)}</td>
                </tr>
                {open === a.id && <tr><td colSpan={6} className="bg-slate-50 px-4 py-2"><AuditChanges a={a} /><details className="mt-1 text-xs"><summary className="cursor-pointer text-slate-500">Raw JSON</summary><pre className="overflow-x-auto whitespace-pre-wrap">{JSON.stringify({ previous: a.previous_value, new: a.new_value }, null, 2)}</pre></details></td></tr>}
              </Fragment>
            ))}</tbody>
          </table>
        )}
      </div>
      {data && data.total > PAGE && <div className="mt-3 flex items-center justify-end gap-2 text-sm"><span className="text-slate-500">{page * PAGE + 1}–{Math.min((page + 1) * PAGE, data.total)} of {data.total}</span><button className="btn-secondary" disabled={!page} onClick={() => setPage(page - 1)}>Previous</button><button className="btn-secondary" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>Next</button></div>}
    </div>
  )
}
