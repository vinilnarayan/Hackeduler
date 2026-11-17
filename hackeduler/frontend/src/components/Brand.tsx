import { Mail } from 'lucide-react'
import { Modal } from './ui'

export const CREDIT = 'OffSec Team, InfoSec, IBS Group'
export const CONTACT_EMAIL = 'OffSec_Team@ibsplc.com'

/** The Hackeduler logo (black glyph on transparent), on a light tile so it reads on dark backgrounds too. */
export function Logo({ className = 'h-9 w-9', tile = false }: { className?: string; tile?: boolean }) {
  return <img src="/logo.png" alt="" aria-hidden width={512} height={512} className={`${className} shrink-0 object-contain ${tile ? 'rounded-lg bg-white p-1' : ''}`} />
}

export function AboutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="About Hackeduler" size="sm" footer={<button className="btn-primary" onClick={onClose}>Close</button>}>
      <div className="space-y-3 text-center text-sm">
        <Logo className="mx-auto h-24 w-24" />
        <div>
          <div className="text-lg font-semibold">Hackeduler</div>
          <div className="text-slate-600">Security testing capacity scheduling</div>
        </div>
        <p>Designed and developed by<br /><span className="font-medium">{CREDIT}</span></p>
        <p className="flex items-center justify-center gap-1.5">
          <Mail className="h-4 w-4 text-slate-500" aria-hidden />
          <a className="text-blue-700 underline" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </p>
      </div>
    </Modal>
  )
}
