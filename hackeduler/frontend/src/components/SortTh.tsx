import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'

export type SortDir = 'asc' | 'desc'
export interface SortState { key: string; dir: SortDir }
type Val = string | number | boolean | null | undefined

const cmp = (a: Val, b: Val): number => {
  const na = a === null || a === undefined || a === ''
  const nb = b === null || b === undefined || b === ''
  if (na || nb) return na === nb ? 0 : na ? 1 : -1          // empty values always last (handled again for desc)
  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (typeof a === 'boolean' || typeof b === 'boolean') return Number(a) - Number(b)
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
}

/** Client-side sorting for a table: `accessors` map a column key to the value to sort on. Click a header to
 *  sort ascending, again for descending, a third time to go back to the original order. */
export function useSort<T>(rows: T[] | null | undefined, accessors: Record<string, (r: T) => Val>, initial: SortState | null = null) {
  const [sort, setSort] = useState<SortState | null>(initial)
  const sorted = useMemo(() => {
    if (!rows || !sort || !accessors[sort.key]) return rows ?? []
    const get = accessors[sort.key]
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((x, y) => {
      const a = get(x), b = get(y)
      const ea = a === null || a === undefined || a === '', eb = b === null || b === undefined || b === ''
      if (ea || eb) return ea === eb ? 0 : ea ? 1 : -1       // empty last in both directions
      return dir * cmp(a, b)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sort])
  const toggle = (key: string) => setSort((s) => (!s || s.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null))
  return { sorted, sort, toggle }
}

/** A column header that sorts the table when clicked. */
export function SortTh({ label, k, sort, onToggle, className = 'th' }: { label: string; k: string; sort: SortState | null; onToggle: (k: string) => void; className?: string }) {
  const active = sort?.key === k
  const Icon = !active ? ChevronsUpDown : sort!.dir === 'asc' ? ArrowUp : ArrowDown
  return (
    <th className={className} aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="inline-flex items-center gap-1 uppercase hover:text-slate-800" onClick={() => onToggle(k)} aria-label={`Sort by ${label}`}>
        {label}<Icon className={`h-3 w-3 ${active ? 'text-slate-800' : 'text-slate-300'}`} aria-hidden />
      </button>
    </th>
  )
}
