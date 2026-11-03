import { useNavigate } from 'react-router-dom'
import { get } from '../../api/client'
import type { ActivityType } from '../../api/types'
import { ResourceCalendar } from '../../components/ResourceCalendar'
import { PageHeader } from '../../components/ui'
import { useAsync } from '../../lib/useAsync'

export default function CalendarPage() {
  const nav = useNavigate()
  const acts = useAsync<ActivityType[]>(() => get('/api/activity-types'))
  return (
    <div>
      <PageHeader title="Availability Calendar" subtitle="Anonymous resource availability. Select a green day to request that resource; choose an activity type to highlight days where it would not fit (yellow)." />
      <ResourceCalendar mode="requester" activityTypes={acts.data ?? []}
        onCellClick={(r, cell) => cell.mine ? nav('/my-bookings') : nav(`/book?resource=${r.id}&start=${cell.date}`)} />
    </div>
  )
}
