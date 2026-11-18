import { useEffect, useRef, useState } from 'react'

type Props = { value: string; resetKey: string; onChange: (html: string) => void; variables: string[] }

const exec = (cmd: string, arg?: string) => { try { document.execCommand?.(cmd, false, arg) } catch { /* not supported */ } }

/** Visual editor for an email body. Produces simple HTML; the server cleans it again and writes the final styles. */
export default function RichEmailEditor({ value, resetKey, onChange, variables }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const saved = useRef<Range | null>(null)
  const [url, setUrl] = useState('')
  const [urlErr, setUrlErr] = useState('')

  // Load the template into the editor when a different one is opened (not on every keystroke, which would move the cursor).
  useEffect(() => { if (ref.current) ref.current.innerHTML = value }, [resetKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const keep = () => { const s = window.getSelection(); if (s?.rangeCount && ref.current?.contains(s.anchorNode)) saved.current = s.getRangeAt(0).cloneRange() }
    document.addEventListener('selectionchange', keep)
    return () => document.removeEventListener('selectionchange', keep)
  }, [])

  const emit = () => onChange(ref.current?.innerHTML ?? '')
  const run = (fn: () => void) => { ref.current?.focus(); fn(); emit() }
  const keepFocus = (e: React.MouseEvent) => e.preventDefault()          // clicking a toolbar button must not drop the selection
  const btn = 'btn-secondary min-w-9 px-2 py-1 text-sm'

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
        <button type="button" className={btn} aria-label="Details table" onMouseDown={keepFocus}
          onClick={() => run(() => exec('insertHTML', '<table class="kv"><tbody><tr><td>Label</td><td>Value</td></tr><tr><td>Label</td><td>Value</td></tr></tbody></table><p><br></p>'))}>Details table</button>
        <button type="button" className={btn} aria-label="Button" onMouseDown={keepFocus}
          onClick={() => run(() => exec('insertHTML', '<a class="btn" href="https://">Button text</a>&nbsp;'))}>Button</button>
      </div>
      <div className="flex flex-wrap items-start gap-1">
        <div className="min-w-0 flex-1">
          <input className="input text-xs" aria-label="Link address" placeholder="Link address, e.g. https://hackeduler.example/bookings" value={url} onChange={(e) => setUrl(e.target.value)} />
          {urlErr && <p className="mt-1 text-xs text-red-600">{urlErr}</p>}
        </div>
        <button type="button" className={btn} onMouseDown={keepFocus} onClick={addLink}>Make link</button>
      </div>
      <div ref={ref} contentEditable suppressContentEditableWarning role="textbox" aria-multiline aria-label="Email body" data-testid="rich-editor"
        className="email-editor min-h-72 rounded border border-slate-300 bg-white p-3 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
        onInput={emit}
        onPaste={(e) => { e.preventDefault(); const t = e.clipboardData.getData('text/plain'); exec('insertText', t); emit() }} />
      <div>
        <div className="mb-1 text-xs text-slate-500">Click a variable to insert it where the cursor is:</div>
        <div className="flex flex-wrap gap-1">{variables.map((v) => (
          <button type="button" key={v} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs hover:bg-blue-50" onMouseDown={keepFocus}
            onClick={() => run(() => exec('insertText', `{{${v}}}`))}>{v}</button>
        ))}</div>
      </div>
    </div>
  )
}
