/** Email template designs and colours (the server accepts exactly these layouts and any #rrggbb colour). */
export const LAYOUTS = [
  { id: 'classic', label: 'Classic', hint: 'Coloured header bar' },
  { id: 'minimal', label: 'Minimal', hint: 'White header, coloured line' },
  { id: 'banner', label: 'Banner', hint: 'Large header showing the subject' },
] as const

export const COLOURS = [
  { hex: '#0f2744', name: 'Navy' }, { hex: '#1f5fd1', name: 'Blue' }, { hex: '#0e7490', name: 'Cyan' },
  { hex: '#0f766e', name: 'Teal' }, { hex: '#15803d', name: 'Green' }, { hex: '#4d7c0f', name: 'Olive' },
  { hex: '#b45309', name: 'Amber' }, { hex: '#9a3412', name: 'Rust' }, { hex: '#b91c1c', name: 'Red' },
  { hex: '#be185d', name: 'Pink' }, { hex: '#7e22ce', name: 'Purple' }, { hex: '#4338ca', name: 'Indigo' },
  { hex: '#334155', name: 'Slate' }, { hex: '#111827', name: 'Black' },
] as const

export const isHex = (v: string) => /^#[0-9a-fA-F]{6}$/.test(v)

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const inline = (s: string) =>
  esc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>')

/** Older plain-text templates (**bold**, [link](url), "- " bullets, "# " heading, blank line = paragraph) -> editor HTML. */
export function textToHtml(text: string): string {
  const out: string[] = []
  let para: string[] = []
  let items: string[] = []
  const flush = () => {
    if (para.length) out.push(`<p>${para.map(inline).join('<br>')}</p>`)
    if (items.length) out.push(`<ul>${items.map((i) => `<li>${inline(i)}</li>`).join('')}</ul>`)
    para = []; items = []
  }
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    if (!line.trim()) flush()
    else if (bullet) { if (para.length) flush(); items.push(bullet[1]) }
    else if (/^#{1,3}\s+/.test(line)) { flush(); out.push(`<h2>${inline(line.replace(/^#{1,3}\s+/, ''))}</h2>`) }
    else { if (items.length) flush(); para.push(line) }
  }
  flush()
  return out.join('')
}
