import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import type { ForcePayload, OverrideDetails } from '../api/types'
import { useAuth } from '../lib/auth'
import { fmt } from '../lib/dates'
import { Modal, StatusBadge } from './ui'

/**
 * Admin-only Force Allocate confirmation. Renders nothing for non-admins (the backend
 * independently rejects any non-admin Force Allocate attempt with 403).
 * Requires: the warning to be displayed, a mandatory reason, and an explicit confirmation checkbox.
 */
export function ForceAllocateDialog({ open, details, onClose, onConfirm }: {
  open: boolean; details: OverrideDetails | null; onClose: () => void; onConfirm: (force: ForcePayload) => Promise<void>
}) {
  const { user } = useAuth()
  const [reason, setReason] = useState('')
  const [ack, setAck] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) { setReason(''); setAck(false) } }, [open])
  if (user?.role !== 'admin' || !details) return null
  return (
    <Modal open={open} onClose={onClose} size="lg" title={<span className="flex items-center gap-2 text-red-700"><ShieldAlert className="h-5 w-5" /> Force Allocate – conflict detected</span>}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-danger" disabled={!ack || !reason.trim() || busy}
          onClick={async () => { setBusy(true); try { await onConfirm({ confirm: true, reason: reason.trim() }) } finally { setBusy(false) } }}>
          {busy ? 'Allocating…' : 'Force Allocate'}
        </button>
      </>}>
      <div className="space-y-4 text-sm">
        <div className="rounded-md border border-red-300 bg-red-50 p-3 font-medium text-red-800" role="alert">{details.warning}</div>
        <div>
          <div className="label">Detected conflicts / restrictions</div>
          <ul className="list-disc space-y-1 pl-5">
            {details.issues.map((i, n) => (
              <li key={n}><span className="font-medium">{i.type.replace(/_/g, ' ')}:</span> {i.message}{i.dates?.length ? <span className="text-slate-500"> ({i.dates.join(', ')})</span> : null}</li>
            ))}
          </ul>
        </div>
        {details.conflicting_bookings.length > 0 && (
          <div>
            <div className="label">Affected bookings (will NOT be modified)</div>
            <div className="overflow-x-auto rounded border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50"><tr><th className="th">Booking</th><th className="th">Application</th><th className="th">Dates</th><th className="th">POC</th><th className="th">Status</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {details.conflicting_bookings.map((b) => (
                    <tr key={b.id}><td className="td font-mono text-xs">{b.id.slice(0, 8)}…</td><td className="td">{b.application_name}</td>
                      <td className="td whitespace-nowrap">{fmt(b.start_date)} – {fmt(b.end_date)}</td><td className="td">{b.poc_name}<div className="text-xs text-slate-500">{b.poc_email}</div></td>
                      <td className="td"><StatusBadge status={b.status as any} /></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-xs text-slate-500">Affected POCs of approved bookings will be notified. The overlap stays visible as an open conflict until resolved.</p>
          </div>
        )}
        <div className="text-xs text-slate-600">Proposed allocation: {fmt(details.plan.start_date)} – {fmt(details.plan.end_date)} ({details.plan.duration_days} working days)</div>
        <div>
          <label className="label" htmlFor="force-reason">Override reason *</label>
          <textarea id="force-reason" className="input min-h-20" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000}
            placeholder="e.g. CISO-approved emergency assessment for regulatory deadline" />
        </div>
        <label className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3">
          <input type="checkbox" className="mt-0.5" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>I confirm that I have reviewed the conflict and have authorization to proceed. This action is recorded in the immutable audit trail.</span>
        </label>
      </div>
    </Modal>
  )
}
