import { useState, type ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import {
  AlertTriangle, BarChart3, CalendarDays, CalendarPlus, ClipboardList, FileClock, GitPullRequestArrow, LogOut, Mail, Menu,
  PartyPopper, Plane, Settings, ShieldCheck, Fingerprint, SlidersHorizontal, Users, UserCog, X, LayoutDashboard, ListChecks,
} from 'lucide-react'
import { useAuth } from '../lib/auth'

interface NavItem { to: string; label: string; icon: ReactNode }

const REQUESTER_NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: <LayoutDashboard className="h-4 w-4" /> },
  { to: '/calendar', label: 'Availability Calendar', icon: <CalendarDays className="h-4 w-4" /> },
  { to: '/book', label: 'New Booking', icon: <CalendarPlus className="h-4 w-4" /> },
  { to: '/my-bookings', label: 'My Bookings', icon: <ClipboardList className="h-4 w-4" /> },
]

const ADMIN_NAV: { section: string; items: NavItem[] }[] = [
  { section: 'Overview', items: [
    { to: '/admin', label: 'Dashboard', icon: <BarChart3 className="h-4 w-4" /> },
    { to: '/admin/calendar', label: 'Resource Calendar', icon: <CalendarDays className="h-4 w-4" /> },
  ] },
  { section: 'Bookings', items: [
    { to: '/admin/bookings', label: 'Bookings', icon: <ListChecks className="h-4 w-4" /> },
    { to: '/admin/bookings/new', label: 'Manual Allocation', icon: <CalendarPlus className="h-4 w-4" /> },
    { to: '/admin/change-requests', label: 'Change Requests', icon: <GitPullRequestArrow className="h-4 w-4" /> },
    { to: '/admin/conflicts', label: 'Conflicts', icon: <AlertTriangle className="h-4 w-4" /> },
  ] },
  { section: 'Team & Calendar', items: [
    { to: '/admin/resources', label: 'Resources', icon: <UserCog className="h-4 w-4" /> },
    { to: '/admin/leave', label: 'Leave', icon: <Plane className="h-4 w-4" /> },
    { to: '/admin/holidays', label: 'Holidays', icon: <PartyPopper className="h-4 w-4" /> },
    { to: '/admin/activity-types', label: 'Activity Types', icon: <SlidersHorizontal className="h-4 w-4" /> },
  ] },
  { section: 'Administration', items: [
    { to: '/admin/audit', label: 'Audit Log', icon: <FileClock className="h-4 w-4" /> },
    { to: '/admin/email', label: 'Email & Templates', icon: <Mail className="h-4 w-4" /> },
    { to: '/admin/users', label: 'Users', icon: <Users className="h-4 w-4" /> },
    { to: '/admin/sso', label: 'Single Sign-On', icon: <Fingerprint className="h-4 w-4" /> },
    { to: '/admin/settings', label: 'Settings', icon: <Settings className="h-4 w-4" /> },
  ] },
]

function Link({ item, onNav }: { item: NavItem; onNav: () => void }) {
  return (
    <NavLink to={item.to} end onClick={onNav}
      className={({ isActive }) => `flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${isActive ? 'bg-blue-700 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'}`}>
      {item.icon}{item.label}
    </NavLink>
  )
}

export function Layout() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const isAdmin = user?.role === 'admin'
  const sidebar = (
    <nav aria-label="Main navigation" className="flex h-full flex-col gap-4 overflow-y-auto bg-slate-900 p-3">
      <div className="flex items-center gap-2 px-2 py-1 text-white">
        <ShieldCheck className="h-6 w-6 text-sky-400" />
        <div><div className="text-sm font-semibold leading-tight">OffSec Resource Planner</div><div className="text-[11px] text-slate-400">{isAdmin ? 'Administrator' : 'Requester'}</div></div>
      </div>
      {isAdmin ? ADMIN_NAV.map((s) => (
        <div key={s.section}>
          <div className="px-3 pb-1 text-[10px] font-semibold tracking-wider text-slate-500 uppercase">{s.section}</div>
          <div className="space-y-0.5">{s.items.map((i) => <Link key={i.to} item={i} onNav={() => setOpen(false)} />)}</div>
        </div>
      )) : (
        <div className="space-y-0.5">{REQUESTER_NAV.map((i) => <Link key={i.to} item={i} onNav={() => setOpen(false)} />)}</div>
      )}
      {isAdmin && (
        <div>
          <div className="px-3 pb-1 text-[10px] font-semibold tracking-wider text-slate-500 uppercase">Requester view</div>
          <Link item={{ to: '/calendar', label: 'Anonymous Calendar', icon: <CalendarDays className="h-4 w-4" /> }} onNav={() => setOpen(false)} />
        </div>
      )}
    </nav>
  )
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">Skip to content</a>
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <div className="w-64">{sidebar}</div>
          <button aria-label="Close menu" className="flex-1 bg-slate-900/50" onClick={() => setOpen(false)} />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur">
          <button className="btn-ghost p-1.5 lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}>{open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}</button>
          <div className="flex-1" />
          <div className="text-right text-sm">
            <div className="font-medium">{user?.full_name}</div>
            <div className="text-xs text-slate-500">{user?.email}</div>
          </div>
          <button className="btn-secondary" onClick={() => logout()} aria-label="Sign out"><LogOut className="h-4 w-4" /><span className="hidden sm:inline">Sign out</span></button>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 p-4 sm:p-6"><Outlet /></main>
      </div>
    </div>
  )
}
