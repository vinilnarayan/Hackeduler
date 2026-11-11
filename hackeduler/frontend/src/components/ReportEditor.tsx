import { useState } from 'react'
import { put, validationMessage } from '../api/client'
import type { Booking, ReportType } from '../api/types'
import { fmtDateTime } from '../lib/dates'
import { useToast } from '../lib/toast'
import { Field, ReportBadge } from './ui'

/** Report-sharing form: shared yes/no, V1 or Met, and comments. Used by the assigned engineer and by admins. */
export function ReportEditor({ booking, url, onSaved }: { booking: Booking; url: string; onSaved: (b: Booking) => void }) {
  const toast = useToast()
  const [shared, setShared] = useState(booking.report_shared)
  const [type, setType] = useState<ReportType | ''>(booking.report_type ?? '')
  const [comments, setComments] = useState(booking.report_comments ?? '')
  const [busy, setBusy] = useState(false)
  const dirty = shared !== booking.report_shared || type !== (booking.report_type ?? '') || comments !== (booking.report_comments ?? '')
  const save = async () => {
    setBusy(true)
    try {
      const b = await put<Booking>(url, { report_shared: shared, report_type: type || null, report_comments: comments || null })
      toast('success', 'Report details saved'); onSaved(b)
    } catch (e) { toast('error', validationMessage(e)) } finally { setBusy(false) }
  }
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 p-3">
      <div className="flex items-center justify-between"><div className="text-sm font-semibold">Report</div><ReportBadge shared={booking.report_shared} type={booking.report_type} /></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />Report shared</label>
      <Field label={shared ? 'Report type *' : 'Report type'} htmlFor="rp-type">
        <select id="rp-type" className="input" value={type} onChange={(e) => setType(e.target.value as ReportType | '')}>
          <option value="">— Select —</option><option value="V1">V1 report</option><option value="Met">Met report</option>
        </select>
      </Field>
      <Field label="Comments" htmlFor="rp-c"><textarea id="rp-c" className="input min-h-24" maxLength={5000} value={comments} onChange={(e) => setComments(e.target.value)} /></Field>
      {booking.report_shared_at && booking.report_shared && <div className="text-xs text-slate-500">Shared on {fmtDateTime(booking.report_shared_at)}</div>}
      <div className="flex justify-end"><button className="btn-primary" disabled={busy || !dirty || (shared && !type)} onClick={save}>{busy ? 'Saving…' : 'Save report details'}</button></div>
    </div>
  )
}
