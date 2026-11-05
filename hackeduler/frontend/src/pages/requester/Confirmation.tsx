import { Link, useParams } from 'react-router-dom'
import { CheckCircle2 } from 'lucide-react'
import { get } from '../../api/client'
import type { Booking } from '../../api/types'
import { ErrorState, KV, Spinner, StatusBadge } from '../../components/ui'
import { fmt, fmtDateTime } from '../../lib/dates'
import { useAsync } from '../../lib/useAsync'

export default function BookingConfirmation() {
  const { id } = useParams()
  const { data: b, error, loading } = useAsync<Booking>(() => get(`/api/bookings/${id}`), [id])
  if (error) return <ErrorState message={error} />
  if (loading || !b) return <Spinner />
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="card p-6 text-center">
        <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" />
        <h1 className="mt-2 text-xl font-semibold">Booking request submitted</h1>
        <p className="text-sm text-slate-600">The OffSec team has been notified. The slot is reserved for you while the request is pending{b.expires_at ? ` (until ${fmtDateTime(b.expires_at)})` : ''}.</p>
        <div className="mt-4 rounded-md bg-slate-100 p-3"><div className="text-xs text-slate-500">Booking ID</div><div className="font-mono text-sm font-semibold break-all select-all">{b.id}</div></div>
      </div>
      <div className="card p-4">
        <KV items={[
          ['Status', <StatusBadge status={b.status} />], ['Resource', b.requires_resource ? b.resource_display_name : 'Not required'], ['Product / implementation', [b.product_name, b.implementation_name].filter(Boolean).join(' · ') || '—'],
          ['Application', `${b.application_name} v${b.application_version}`], ['Activity type', b.activity_name],
          ['Start date', fmt(b.start_date)], ['Expected end date', fmt(b.end_date)], ['Duration', b.duration_days ? `${b.duration_days} working days` : '—'],
          ['PCI DSS scope', b.pci_dss_scope ? 'Yes' : 'No'], ['POC', `${b.poc_name} <${b.poc_email}>`], ['Submitted', fmtDateTime(b.submitted_at)],
        ]} />
      </div>
      <div className="flex justify-center gap-2"><Link className="btn-secondary" to="/my-bookings">View my bookings</Link><Link className="btn-primary" to="/book">New request</Link></div>
    </div>
  )
}
