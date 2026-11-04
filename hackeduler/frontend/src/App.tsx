import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import Login from './pages/Login'
import RequesterDashboard from './pages/requester/Dashboard'
import CalendarPage from './pages/requester/CalendarPage'
import NewBooking from './pages/requester/NewBooking'
import MyBookings from './pages/requester/MyBookings'
import BookingConfirmation from './pages/requester/Confirmation'
const AdminDashboard = lazy(() => import('./pages/admin/Dashboard'))
const AdminCalendar = lazy(() => import('./pages/admin/AdminCalendar'))
const AdminBookings = lazy(() => import('./pages/admin/Bookings'))
const ManualAllocation = lazy(() => import('./pages/admin/ManualAllocation'))
const ChangeRequests = lazy(() => import('./pages/admin/ChangeRequests'))
const Conflicts = lazy(() => import('./pages/admin/Conflicts'))
const Resources = lazy(() => import('./pages/admin/Resources'))
const LeavePage = lazy(() => import('./pages/admin/Leave'))
const Holidays = lazy(() => import('./pages/admin/Holidays'))
const ActivityTypes = lazy(() => import('./pages/admin/ActivityTypes'))
const AuditLog = lazy(() => import('./pages/admin/AuditLog'))
const EmailPage = lazy(() => import('./pages/admin/Email'))
const UsersPage = lazy(() => import('./pages/admin/Users'))
const SettingsPage = lazy(() => import('./pages/admin/Settings'))
const SSOPage = lazy(() => import('./pages/admin/SSO'))
import { lazy, Suspense, type ReactNode } from 'react'

/** UI-level guard only; every admin API is independently protected by the backend. */
function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  return user?.role === 'admin' ? <Suspense fallback={<Spinner />}>{children}</Suspense> : <Navigate to="/" replace />
}

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Spinner label="Loading session…" />
  if (!user) return <Routes><Route path="*" element={<Login />} /></Routes>
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={user.role === 'admin' ? <Navigate to="/admin" replace /> : <RequesterDashboard />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="book" element={<NewBooking />} />
        <Route path="my-bookings" element={<MyBookings />} />
        <Route path="bookings/:id/confirmation" element={<BookingConfirmation />} />
        <Route path="admin" element={<AdminOnly><AdminDashboard /></AdminOnly>} />
        <Route path="admin/calendar" element={<AdminOnly><AdminCalendar /></AdminOnly>} />
        <Route path="admin/bookings" element={<AdminOnly><AdminBookings /></AdminOnly>} />
        <Route path="admin/bookings/new" element={<AdminOnly><ManualAllocation /></AdminOnly>} />
        <Route path="admin/change-requests" element={<AdminOnly><ChangeRequests /></AdminOnly>} />
        <Route path="admin/conflicts" element={<AdminOnly><Conflicts /></AdminOnly>} />
        <Route path="admin/resources" element={<AdminOnly><Resources /></AdminOnly>} />
        <Route path="admin/leave" element={<AdminOnly><LeavePage /></AdminOnly>} />
        <Route path="admin/holidays" element={<AdminOnly><Holidays /></AdminOnly>} />
        <Route path="admin/activity-types" element={<AdminOnly><ActivityTypes /></AdminOnly>} />
        <Route path="admin/audit" element={<AdminOnly><AuditLog /></AdminOnly>} />
        <Route path="admin/email" element={<AdminOnly><EmailPage /></AdminOnly>} />
        <Route path="admin/users" element={<AdminOnly><UsersPage /></AdminOnly>} />
        <Route path="admin/settings" element={<AdminOnly><SettingsPage /></AdminOnly>} />
        <Route path="admin/sso" element={<AdminOnly><SSOPage /></AdminOnly>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
