import { useEffect, useState } from 'react'
import { Modal } from './ui'

/** Generic confirmation dialog, optionally requiring a reason (rejection, cancellation, etc.). */
export function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', tone = 'primary', requireReason, reasonLabel = 'Reason', onConfirm, onClose }: {
  open: boolean; title: string; message: React.ReactNode; confirmLabel?: string; tone?: 'primary' | 'danger' | 'success' | 'warning'
  requireReason?: boolean; reasonLabel?: string; onConfirm: (reason: string) => Promise<void> | void; onClose: () => void
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) setReason('') }, [open])
  const disabled = busy || (requireReason && !reason.trim())
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm"
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Back</button>
        <button className={`btn-${tone}`} disabled={!!disabled} onClick={async () => { setBusy(true); try { await onConfirm(reason.trim()) } finally { setBusy(false) } }}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </>}>
      <div className="space-y-3 text-sm">
        <div>{message}</div>
        {requireReason !== undefined && (
          <div>
            <label className="label" htmlFor="confirm-reason">{reasonLabel}{requireReason && ' *'}</label>
            <textarea id="confirm-reason" className="input min-h-24" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
          </div>
        )}
      </div>
    </Modal>
  )
}
