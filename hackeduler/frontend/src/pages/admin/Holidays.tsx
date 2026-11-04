import { useRef, useState } from 'react'
import { Plus, Upload } from 'lucide-react'
import { format, getDay, startOfMonth, getDaysInMonth } from 'date-fns'
import { api, del, get, patch, post, validationMessage } from '../../api/client'
import type { Holiday } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Spinner } from '../../components/ui'
import { fmt, iso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function Holidays() {
  const toast = useToast()
  const [year, setYear] = useState(new Date().getFullYear())
  const { data, error, loading, reload } = useAsync<Holiday[]>(() => get(`/api/admin/holidays?year=${year}`), [year])
  const [edit, setEdit] = useState<Partial<Holiday> | null>(null)
  const [remove, setRemove] = useState<Holiday | null>(null)
  const [importRes, setImportRes] = useState<any>(null)
  const file = useRef<HTMLInputElement>(null)
  const flagged = (r: any) => r?.flagged_bookings?.length && toast('info', `${r.flagged_bookings.length} booking(s) flagged for review – see Conflicts`)
  const save = async () => {
    try {
      const body = { name: edit!.name, holiday_date: edit!.holiday_date, description: edit!.description || null }
      const r = edit!.id ? await patch(`/api/admin/holidays/${edit!.id}`, body) : await post('/api/admin/holidays', body)
      toast('success', 'Holiday saved'); flagged(r); setEdit(null); reload()
    } catch (e) { toast('error', validationMessage(e)) }
  }
  const doImport = async (f: File) => {
    const fd = new FormData(); fd.append('file', f)
    try { const r = await api('POST', '/api/admin/holidays/import', fd); setImportRes(r); flagged(r); reload() } catch (e) { toast('error', validationMessage(e)) }
    if (file.current) file.current.value = ''
  }
  const byDate = new Map((data ?? []).map((h) => [h.holiday_date, h]))
  return (
    <div>
      <PageHeader title="Organisation Holidays" subtitle="Holidays apply to every resource and are excluded from working-day calculations. Affected bookings are flagged for review."
        actions={<>
          <input ref={file} type="file" accept=".csv,.xlsx" className="hidden" onChange={(e) => e.target.files?.[0] && doImport(e.target.files[0])} />
          <button className="btn-secondary" onClick={() => file.current?.click()}><Upload className="h-4 w-4" />Import CSV / Excel</button>
          <button className="btn-primary" onClick={() => setEdit({ holiday_date: `${year}-01-01` })}><Plus className="h-4 w-4" />Add holiday</button>
        </>} />
      <div className="mb-3 flex items-center gap-2"><button className="btn-secondary" onClick={() => setYear(year - 1)} aria-label="Previous year">‹</button><span className="w-16 text-center font-semibold">{year}</span><button className="btn-secondary" onClick={() => setYear(year + 1)} aria-label="Next year">›</button>
        <span className="ml-3 text-xs text-slate-500">Import format: columns <code>name, date, description</code> (date as YYYY-MM-DD or DD/MM/YYYY).</span></div>
      {importRes && <div className="card mb-3 p-3 text-sm">Import: <b>{importRes.created}</b> created, <b>{importRes.updated}</b> updated, <b>{importRes.errors.length}</b> errors.{importRes.errors.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-red-700">{importRes.errors.map((e: any) => <li key={e.row}>Row {e.row}: {e.error}</li>)}</ul>}</div>}
      {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : (
        <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {Array.from({ length: 12 }, (_, m) => <MonthGrid key={m} year={year} month={m} byDate={byDate} onPick={(d) => setEdit(byDate.get(d) ?? { holiday_date: d })} />)}
          </div>
          <div className="card self-start">
            <div className="border-b border-slate-200 px-4 py-2 text-sm font-semibold">{data?.length ?? 0} holidays in {year}</div>
            {!data?.length ? <Empty title="No holidays" /> : (
              <ul className="divide-y divide-slate-100 text-sm">{data.map((h) => (
                <li key={h.id} className="flex items-center gap-2 px-4 py-2"><div className="flex-1"><div className="font-medium">{h.name}</div><div className="text-xs text-slate-500">{fmt(h.holiday_date, 'EEE dd MMM yyyy')}{h.description ? ` · ${h.description}` : ''}</div></div>
                  <button className="btn-ghost px-2 text-xs" onClick={() => setEdit(h)}>Edit</button><button className="btn-ghost px-2 text-xs text-red-700" onClick={() => setRemove(h)}>Delete</button></li>
              ))}</ul>
            )}
          </div>
        </div>
      )}
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? 'Edit holiday' : 'Add holiday'} size="sm"
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" disabled={!edit?.name?.trim() || !edit?.holiday_date} onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          <Field label="Name *" htmlFor="h-n"><input id="h-n" className="input" value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Date *" htmlFor="h-d"><input id="h-d" type="date" className="input" value={edit.holiday_date ?? ''} onChange={(e) => setEdit({ ...edit, holiday_date: e.target.value })} /></Field>
          <Field label="Description" htmlFor="h-de"><textarea id="h-de" className="input" value={edit.description ?? ''} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
        </div>}
      </Modal>
      <ConfirmDialog open={!!remove} onClose={() => setRemove(null)} title="Delete holiday" tone="danger" confirmLabel="Delete"
        message={`Delete “${remove?.name}” on ${fmt(remove?.holiday_date)}? Bookings spanning this date will be flagged for schedule review (they are not changed).`}
        onConfirm={async () => { try { const r = await del(`/api/admin/holidays/${remove!.id}`); toast('success', 'Holiday deleted'); flagged(r); setRemove(null); reload() } catch (e) { toast('error', validationMessage(e)) } }} />
    </div>
  )
}

function MonthGrid({ year, month, byDate, onPick }: { year: number; month: number; byDate: Map<string, Holiday>; onPick: (d: string) => void }) {
  const first = startOfMonth(new Date(year, month, 1))
  const lead = (getDay(first) + 6) % 7
  const n = getDaysInMonth(first)
  return (
    <div className="card p-3">
      <div className="mb-1 text-sm font-semibold">{format(first, 'MMMM')}</div>
      <div className="grid grid-cols-7 gap-0.5 text-center text-[11px]">
        {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => <div key={i} className="font-medium text-slate-400">{d}</div>)}
        {Array.from({ length: lead }, (_, i) => <div key={'x' + i} />)}
        {Array.from({ length: n }, (_, i) => {
          const d = iso(new Date(year, month, i + 1)); const h = byDate.get(d); const wk = (lead + i) % 7 >= 5
          return <button key={d} title={h?.name ?? ''} aria-label={`${d}${h ? `: ${h.name}` : ''}`} onClick={() => onPick(d)}
            className={`rounded py-0.5 ${h ? 'bg-slate-700 font-semibold text-white' : wk ? 'bg-slate-100 text-slate-400' : 'hover:bg-blue-50'}`}>{i + 1}</button>
        })}
      </div>
    </div>
  )
}
