import { useEffect, useRef, useState } from 'react'

type Props = { value: string; resetKey: string; onChange: (html: string) => void; variables?: string[]; variant?: 'template' | 'details'; label?: string }

const currentCell = (): HTMLTableCellElement | null => {
  const n = window.getSelection()?.anchorNode
  const el = n && (n.nodeType === 3 ? n.parentElement : (n as Element))
  return (el && (el as Element).closest?.('td,th')) || null
}

const exec = (cmd: string, arg?: string) => { try { document.execCommand?.(cmd, false, arg) } catch { /* not supported */ } }

/** Visual editor for an email body. Produces simple HTML; the server cleans it again and writes the final styles. */
export default function RichEmailEditor({ value, resetKey, onChange, variables = [], variant = 'template', label = 'Email body' }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const saved = useRef<Range | null>(null)
  const [url, setUrl] = useState('')
  const [urlErr, setUrlErr] = useState('')
  const [rows, setRows] = useState(3)
  const [cols, setCols] = useState(3)
  const [inCell, setInCell] = useState(false)
  const details = variant === 'details'

  // Load the template into the editor when a different one is opened (not on every keystroke, which would move the cursor).
  useEffect(() => { if (ref.current) ref.current.innerHTML = value }, [resetKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const keep = () => { const s = window.getSelection(); if (s?.rangeCount && ref.current?.contains(s.anchorNode)) { saved.current = s.getRangeAt(0).cloneRange(); setInCell(!!currentCell()) } }
    document.addEventListener('selectionchange', keep)
    return () => document.removeEventListener('selectionchange', keep)
  }, [])

  const emit = () => onChange(ref.current?.innerHTML ?? '')
  const run = (fn: () => void) => { ref.current?.focus(); fn(); emit() }
  const keepFocus = (e: React.MouseEvent) => e.preventDefault()          // clicking a toolbar button must not drop the selection
  const btn = 'btn-secondary min-w-9 px-2 py-1 text-sm'

  const cell = (tag: 'td' | 'th', text = '\u00a0') => { const c = document.createElement(tag); c.textContent = text; return c }
  const tableAction = (act: string) => run(() => {
    const td = currentCell(); if (!td) return
    const tr = td.parentElement as HTMLTableRowElement, tb = td.closest('table') as HTMLTableElement
    const idx = Array.from(tr.children).indexOf(td)
    if (act === 'addrow') {
      const n = document.createElement('tr'); Array.from(tr.children).forEach(() => n.appendChild(cell('td')))
      if (tr.parentElement?.tagName === 'THEAD') (tb.tBodies[0] ?? tb.createTBody()).prepend(n); else tr.after(n)
    } else if (act === 'delrow') { if (tb.rows.length > 1) tr.remove(); else tb.remove() }
    else if (act === 'addcol') Array.from(tb.rows).forEach((r) => { const ref = r.children[idx]; if (ref) ref.after(cell(ref.tagName === 'TH' ? 'th' : 'td', ref.tagName === 'TH' ? 'Heading' : '\u00a0')) })
    else if (act === 'delcol') { if (tr.children.length > 1) Array.from(tb.rows).forEach((r) => r.children[idx]?.remove()); else tb.remove() }
    else if (act === 'head') {
      const first = tb.rows[0], isHead = first.children[0].tagName === 'TH'
      Array.from(first.children).forEach((c) => { const n = document.createElement(isHead ? 'td' : 'th'); n.innerHTML = c.innerHTML; c.replaceWith(n) })
    } else if (act === 'deltable') tb.remove()
    setInCell(false)
  })
  const insertTable = () => run(() => {
    const r = Math.min(12, Math.max(1, rows || 3)), c = Math.min(5, Math.max(1, cols || 3))
    const head = `<thead><tr>${'<th>Heading</th>'.repeat(c)}</tr></thead>`
    const body = `<tbody>${`<tr>${'<td>&nbsp;</td>'.repeat(c)}</tr>`.repeat(Math.max(0, r - 1))}</tbody>`
    exec('insertHTML', `<table>${head}${body}</table><p><br></p>`)
  })

  const addLink = () => {
    if (!/^https?:\/\/\S+$/.test(url.trim())) { setUrlErr('Enter a full address starting with http:// or https://'); return }
    setUrlErr('')
    run(() => {
      if (saved.current) { const s = window.getSelection(); s?.removeAllRanges(); s?.addRange(saved.current) }
      exec('createLink', url.trim())
    })
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1" role="toolbar" aria-label="Formatting">
        <button type="button" className={btn} aria-label="Bold" onMouseDown={keepFocus} onClick={() => run(() => exec('bold'))}><b>B</b></button>
        <button type="button" className={btn} aria-label="Italic" onMouseDown={keepFocus} onClick={() => run(() => exec('italic'))}><i>I</i></button>
        <button type="button" className={btn} aria-label="Heading" onMouseDown={keepFocus} onClick={() => run(() => exec('formatBlock', 'h2'))}>Heading</button>
        <button type="button" className={btn} aria-label="Paragraph" onMouseDown={keepFocus} onClick={() => run(() => exec('formatBlock', 'p'))}>Text</button>
        <button type="button" className={btn} aria-label="Bullet list" onMouseDown={keepFocus} onClick={() => run(() => exec('insertUnorderedList'))}>• List</button>
        {!details && <button type="button" className={btn} aria-label="Details table" onMouseDown={keepFocus}
          onClick={() => run(() => exec('insertHTML', '<table class="kv"><tbody><tr><td>Label</td><td>Value</td></tr><tr><td>Label</td><td>Value</td></tr></tbody></table><p><br></p>'))}>Details table</button>}
        {!details && <button type="button" className={btn} aria-label="Button" onMouseDown={keepFocus}
          onClick={() => run(() => exec('insertHTML', '<a class="btn" href="https://">Button text</a>&nbsp;'))}>Button</button>}
      </div>
      {details && <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <label htmlFor={`${resetKey}-rows`}>Rows</label><input id={`${resetKey}-rows`} type="number" min={1} max={12} className="input w-16 py-1" value={rows} onChange={(e) => setRows(Number(e.target.value))} />
          <label htmlFor={`${resetKey}-cols`}>Columns</label><input id={`${resetKey}-cols`} type="number" min={1} max={5} className="input w-16 py-1" value={cols} onChange={(e) => setCols(Number(e.target.value))} />
          <button type="button" className={btn} onMouseDown={keepFocus} onClick={insertTable}>Insert table</button>
        </div>
        <div className="flex flex-wrap items-center gap-1" role="toolbar" aria-label="Table tools">
          <span className="text-xs text-slate-500">Click inside a table cell to edit it:</span>
          {([['addrow', '+ Row'], ['delrow', '− Row'], ['addcol', '+ Column'], ['delcol', '− Column'], ['head', 'Header row on/off'], ['deltable', 'Delete table']] as const).map(([a, t]) => (
            <button key={a} type="button" className={btn} disabled={!inCell} onMouseDown={keepFocus} onClick={() => tableAction(a)}>{t}</button>))}
        </div>
      </div>}
      <div className="flex flex-wrap items-start gap-1">
        <div className="min-w-0 flex-1">
          <input className="input text-xs" aria-label="Link address" placeholder="Link address, e.g. https://hackeduler.example/bookings" value={url} onChange={(e) => setUrl(e.target.value)} />
          {urlErr && <p className="mt-1 text-xs text-red-600">{urlErr}</p>}
        </div>
        <button type="button" className={btn} onMouseDown={keepFocus} onClick={addLink}>Make link</button>
      </div>
      <div ref={ref} contentEditable suppressContentEditableWarning role="textbox" aria-multiline aria-label={label} data-testid="rich-editor"
        className="email-editor min-h-72 rounded border border-slate-300 bg-white p-3 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
        onInput={emit}
        onPaste={(e) => { e.preventDefault(); const t = e.clipboardData.getData('text/plain'); exec('insertText', t); emit() }} />
      {variables.length > 0 && <div>
        <div className="mb-1 text-xs text-slate-500">Click a variable to insert it where the cursor is:</div>
        <div className="flex flex-wrap gap-1">{variables.map((v) => (
          <button type="button" key={v} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs hover:bg-blue-50" onMouseDown={keepFocus}
            onClick={() => run(() => exec('insertText', `{{${v}}}`))}>{v}</button>
        ))}</div>
      </div>}
    </div>
  )
}
