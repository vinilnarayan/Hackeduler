import { useState } from 'react'
import { X } from 'lucide-react'

export const MAX_TAGS = 20
export const MAX_TAG_LEN = 40

/** Chip-style editor for a list of tags. Enter or comma adds, Backspace on an empty box removes the last one. */
export function TagInput({ id, value, onChange, suggestions = [] }: { id?: string; value: string[]; onChange: (v: string[]) => void; suggestions?: string[] }) {
  const [text, setText] = useState('')
  const listId = id ? `${id}-list` : undefined
  const add = (raw: string) => {
    const parts = raw.split(',').map((t) => t.trim().replace(/\s+/g, ' ').slice(0, MAX_TAG_LEN)).filter(Boolean)
    if (!parts.length) { setText(''); return }
    const next = [...value]
    for (const t of parts) if (next.length < MAX_TAGS && !next.some((x) => x.toLowerCase() === t.toLowerCase())) next.push(t)
    onChange(next); setText('')
  }
  return (
    <div className="input flex min-h-9 flex-wrap items-center gap-1 py-1">
      {value.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded bg-indigo-100 px-1.5 py-0.5 text-xs font-medium text-indigo-800">
          {t}<button type="button" className="rounded hover:bg-indigo-200" aria-label={`Remove tag ${t}`} onClick={() => onChange(value.filter((x) => x !== t))}><X className="h-3 w-3" /></button>
        </span>
      ))}
      <input id={id} list={listId} className="min-w-24 flex-1 bg-transparent text-sm outline-none" maxLength={MAX_TAG_LEN} placeholder={value.length ? '' : 'Type a tag, press Enter'}
        value={text} onChange={(e) => (e.target.value.includes(',') ? add(e.target.value) : setText(e.target.value))}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(text) } else if (e.key === 'Backspace' && !text && value.length) onChange(value.slice(0, -1)) }}
        onBlur={() => text.trim() && add(text)} />
      {listId && <datalist id={listId}>{suggestions.filter((s) => !value.some((v) => v.toLowerCase() === s.toLowerCase())).map((s) => <option key={s} value={s} />)}</datalist>}
    </div>
  )
}

/** Every tag used by the given products and their implementations, de-duplicated ignoring case (first spelling wins), sorted. */
export function collectTags(products: { tags?: string[]; implementations: { tags?: string[] }[] }[] | null | undefined): string[] {
  const seen = new Map<string, string>()
  for (const p of products ?? []) for (const t of [...(p.tags ?? []), ...p.implementations.flatMap((i) => i.tags ?? [])]) if (!seen.has(t.toLowerCase())) seen.set(t.toLowerCase(), t)
  return Array.from(seen.values()).sort((a, b) => a.localeCompare(b))
}
