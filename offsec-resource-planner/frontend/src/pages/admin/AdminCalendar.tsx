import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { get } from '../../api/client'
import type { ActivityType } from '../../api/types'
import { AdminBookingModal } from '../../components/AdminBookingModal'
import { ResourceCalendar } from '../../components/ResourceCalendar'
import { PageHeader } from '../../components/ui'
import { useAsync } from '../../lib/useAsync'

export default function AdminCalendar() {
  const nav = useNavigate()
  const acts = useAsync<ActivityType[]>(() => get('/api/admin/activity-types'))
  const [sel, setSel] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  return (
    <div>
      <PageHeader title="Resource Calendar" subtitle="Full view: engineer mapping, approved bookings, pending reservations, leave, holidays and overlaps (⚠). Click a booking to manage it, or a free day to allocate." />
      <ResourceCalendar mode="admin" activityTypes={(acts.data ?? []).filter((a) => a.is_active)} refreshKey={refresh}
        onCellClick={(r, c) => {
          if (c.bookings?.length) setSel(c.bookings[0].id)
          else if (c.state === 'available' || c.state === 'limited' || c.state === 'non_working' || c.state === 'inactive') nav(`/admin/bookings/new?resource=${r.id}&start=${c.date}`)
        }} />
      {sel && <AdminBookingModal bookingId={sel} onClose={() => setSel(null)} onChanged={() => setRefresh((x) => x + 1)} />}
    </div>
  )
}
