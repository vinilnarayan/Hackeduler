import { addDays, format, parseISO, startOfMonth, endOfMonth, startOfWeek, endOfWeek } from 'date-fns'

export const iso = (d: Date) => format(d, 'yyyy-MM-dd')
export const fmt = (s?: string | null, f = 'dd MMM yyyy') => (s ? format(parseISO(s), f) : '—')
export const fmtDateTime = (s?: string | null) => (s ? format(new Date(s), 'dd MMM yyyy, HH:mm') : '—')
export const parse = (s: string) => parseISO(s)

export type View = 'month' | 'week' | 'day'

export function viewRange(anchor: Date, view: View): [Date, Date] {
  if (view === 'month') return [startOfMonth(anchor), endOfMonth(anchor)]
  if (view === 'week') return [startOfWeek(anchor, { weekStartsOn: 1 }), endOfWeek(anchor, { weekStartsOn: 1 })]
  return [anchor, anchor]
}

export function shift(anchor: Date, view: View, dir: 1 | -1): Date {
  if (view === 'month') return new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1)
  if (view === 'week') return addDays(anchor, 7 * dir)
  return addDays(anchor, dir)
}

export function rangeTitle(anchor: Date, view: View): string {
  const [s, e] = viewRange(anchor, view)
  if (view === 'month') return format(anchor, 'MMMM yyyy')
  if (view === 'week') return `${format(s, 'dd MMM')} – ${format(e, 'dd MMM yyyy')}`
  return format(anchor, 'EEEE, dd MMMM yyyy')
}
