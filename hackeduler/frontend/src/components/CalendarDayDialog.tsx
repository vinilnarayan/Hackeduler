import { useEffect, useState } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import { del, post, put, validationMessage } from '../api/client'
import { fmt, iso } from '../lib/dates'
import { useToast } from '../lib/toast'
import { Field, Modal } from './ui'

export interface DayNote { id: string; note: string }
export interface DayLeave { id: string; leave_type: string | null; reason: string | null; start_date?: string; end_date?: string }
export interface DayInfo { date: string; state: string; holiday: string | null; leave: DayLeave | null; notes: DayNote[]; booking_ids: string[] }

/** What a resource user can do from one calendar day: keep private notes, and mark (or cancel) leave. */
export function CalendarDayDialog({ day, leaveTypes, personal, onClose, onChanged }: {
  day: DayInfo | null; leaveTypes: string[]; personal: { year: number; limit: number; used: number } | null
  onClose: () => void; onChanged: () => void
}) {
  const toast = useToast()
  const today = iso(new Date())
  const [text, setText] = useState('')
  const [editing, setEditing] = useState<{ id: string; note: string } | null>(null)
  const [from, setFrom] = useState(''); const [to, setTo] = useState('')
  const [type, setType] = useState('Annual leave'); const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const date = day?.date
  useEffect(() => { if (date) { setText(''); setEditing(null); setFrom(date); setTo(date); setType('Annual leave'); setReason('') } }, [date])
  if (!day) return null
  const past = day.date < today
  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); onChanged() } catch (e) { toast('error', validationMessage(e)) } finally { setBusy(false) } }
  const addNote = () => run(async () => { await post('/api/resource/notes', { note_date: day.date, note: text }); setText(''); toast('success', 'Note saved') })
  const saveEdit = () => run(async () => { await put(`/api/resource/notes/${editing!.id}`, { note: editing!.note }); setEditing(null); toast('success', 'Note updated') })
  const delNote = (id: string) => run(async () => { await del(`/api/resource/notes/${id}`); toast('success', 'Note deleted') })
  const saveLeave = () => run(async () => {
    const r = await post<any>('/api/resource/leaves', { start_date: from, end_date: to, leave_type: type || null, reason: reason.trim() || null })
    toast('success', 'Leave added')
    if (r.overlapping_bookings) toast('info', `Leave saved. ${r.overlapping_bookings} existing booking(s) overlap these dates; their start and end dates are unchanged.`)
    setReason('')
  })
  const cancelLeave = () => run(async () => { await del(`/api/resource/leaves/${day.leave!.id}`); toast('success', 'Leave cancelled') })
  const personalLeft = personal ? Math.max(0, personal.limit - personal.used) : null
  return (
    <Modal open onClose={onClose} title={fmt(day.date, 'EEEE, dd MMM yyyy')} size="md" footer={<button className="btn-secondary" onClick={onClose}>Close</button>}>
      <div className="space-y-5 text-sm">
        {day.holiday && <p className="rounded bg-amber-50 px-3 py-2 text-amber-900">Holiday: {day.holiday}</p>}

        <section aria-label="Notes">
          <h3 className="mb-2 font-semibold">Notes</h3>
          {day.notes.length === 0 && <p className="mb-2 text-slate-500">No notes for this day.</p>}
          <ul className="mb-3 space-y-2">
            {day.notes.map((n) => (
              <li key={n.id} className="rounded border border-slate-200 p-2">
                {editing?.id === n.id ? (
                  <div className="space-y-2">
                    <textarea aria-label="Edit note" className="input" rows={3} maxLength={2000} value={editing.note} onChange={(e) => setEditing({ id: n.id, note: e.target.value })} />
                    <div className="flex gap-2"><button className="btn-primary" disabled={busy || !editing.note.trim()} onClick={saveEdit}>Save</button><button className="btn-secondary" onClick={() => setEditing(null)}>Cancel</button></div>
                  </div>
                ) : (
                  <div className="flex items-start gap-2">
                    <p className="flex-1 whitespace-pre-wrap break-words">{n.note}</p>
                    <button className="btn-ghost" aria-label="Edit note" onClick={() => setEditing({ id: n.id, note: n.note })}><Pencil className="h-4 w-4" /></button>
                    <button className="btn-ghost" aria-label="Delete note" disabled={busy} onClick={() => delNote(n.id)}><Trash2 className="h-4 w-4" /></button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          <Field label="Add a note" htmlFor="cd-note"><textarea id="cd-note" className="input" rows={3} maxLength={2000} placeholder="Only you can see your notes" value={text} onChange={(e) => setText(e.target.value)} /></Field>
          <button className="btn-primary mt-2" disabled={busy || !text.trim()} onClick={addNote}>Add note</button>
        </section>

        <section aria-label="Leave" className="border-t border-slate-200 pt-4">
          <h3 className="mb-2 font-semibold">Leave</h3>
          {day.leave && (
            <div className="mb-3 flex items-center gap-2 rounded bg-sky-50 px-3 py-2 text-sky-900">
              <span className="flex-1">On leave{day.leave.leave_type ? ` · ${day.leave.leave_type}` : ''}{day.leave.start_date ? ` (${fmt(day.leave.start_date)} – ${fmt(day.leave.end_date)})` : ''}{day.leave.reason ? ` – ${day.leave.reason}` : ''}</span>
              {(day.leave.end_date ?? day.date) >= today && <button className="btn-secondary" disabled={busy} onClick={cancelLeave}>Cancel this leave</button>}
            </div>
          )}
          {past ? <p className="text-slate-500">Leave can only be marked for today or later dates.</p> : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="From *" htmlFor="cd-from"><input id="cd-from" type="date" className="input" min={today} value={from} onChange={(e) => { setFrom(e.target.value); if (to < e.target.value) setTo(e.target.value) }} /></Field>
                <Field label="To *" htmlFor="cd-to"><input id="cd-to" type="date" className="input" min={from || today} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
              </div>
              <Field label="Leave type" htmlFor="cd-type" hint={type === 'Personal leave' && personal ? `Personal leave: ${personal.used} of ${personal.limit} days used in ${personal.year} (${personalLeft} left)` : undefined}>
                <select id="cd-type" className="input" value={type} onChange={(e) => setType(e.target.value)}>{leaveTypes.map((t) => <option key={t}>{t}</option>)}</select>
              </Field>
              <Field label="Comment" htmlFor="cd-reason"><textarea id="cd-reason" className="input" rows={2} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
              <button className="btn-primary" disabled={busy || !from || !to} onClick={saveLeave}>Save leave</button>
            </div>
          )}
        </section>
      </div>
    </Modal>
  )
}
