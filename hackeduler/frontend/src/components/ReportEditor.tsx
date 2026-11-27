import { useState } from 'react'
import { put, validationMessage } from '../api/client'
import type { Booking, ReportType } from '../api/types'
import { fmtDateTime } from '../lib/dates'
import { useToast } from '../lib/toast'
import { Field, Modal, ReportBadge } from './ui'

/** Report-sharing form: shared yes/no, V1 or Met, and comments. Used by the assigned engineer and by admins. */
export function ReportEditor({ booking, url, onSaved }: { booking: Booking; url: string; onSaved: (b: Booking) => void }) {
  const toast = useToast()
  const [shared, setShared] = useState(booking.report_shared)
  const [type, setType] = useState<ReportType | ''>(booking.report_type ?? '')
  const [link, setLink] = useState(booking.report_url ?? '')
  const [comments, setComments] = useState(booking.report_comments ?? '')
  const [busy, setBusy] = useState(false)
  const dirty = shared !== booking.report_shared || type !== (booking.report_type ?? '') || comments !== (booking.report_comments ?? '') || link.trim() !== (booking.report_url ?? '')
  const [asking, setAsking] = useState(false)
  const save = async (notify: boolean) => {
    setAsking(false)
    setBusy(true)
    try {
      const b = await put<Booking>(url, { report_shared: shared, report_type: type || null, report_comments: comments || null, report_url: link.trim() || null, notify_poc: notify })
      toast('success', notify ? 'Report details saved; the POC has been emailed' : 'Report details saved'); onSaved(b)
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
      <Field label={shared ? 'Report link (SharePoint URL) *' : 'Report link (SharePoint URL)'} htmlFor="rp-url" hint="Must start with https://. Requesters, resource users and admins open the report from this link.">
        <input id="rp-url" type="url" className="input" maxLength={2000} placeholder="https://contoso.sharepoint.com/sites/…" value={link} onChange={(e) => setLink(e.target.value)} />
      </Field>
      <Field label="Comments" htmlFor="rp-c"><textarea id="rp-c" className="input min-h-24" maxLength={5000} value={comments} onChange={(e) => setComments(e.target.value)} /></Field>
      {booking.report_shared_at && booking.report_shared && <div className="text-xs text-slate-500">Shared on {fmtDateTime(booking.report_shared_at)}</div>}
      <div className="flex justify-end"><button className="btn-primary" disabled={busy || !dirty || (shared && (!type || !link.trim()))} onClick={() => (shared ? setAsking(true) : save(false))}>{busy ? 'Saving…' : 'Save report details'}</button></div>
      <Modal open={asking} onClose={() => setAsking(false)} title="Inform the POC?" size="sm"
        footer={<><button className="btn-secondary" onClick={() => save(false)}>No</button><button className="btn-primary" onClick={() => save(true)}>Yes, send email</button></>}>
        <p className="text-sm">The report details will be saved. Do you want to email the POC that the <b>{type === 'Met' ? 'Met' : 'V1'} report</b> for <b>{booking.application_name} {booking.application_version}</b> has been shared?</p>
        <p className="mt-2 text-xs text-slate-500">To: the POC and the requester. Cc: the Admin notification recipients and the engineers on this booking.</p>
      </Modal>
    </div>
  )
}
