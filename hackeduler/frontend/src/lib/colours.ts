import type { CSSProperties } from 'react'

/** One distinct colour per id (e.g. per booking in a month). Hues step by the golden angle, so any number of ids
 *  get well-spread, never-repeating hues; three lightness bands keep neighbouring hues apart as the count grows.
 *  Text stays dark on a light background for readability. */
export function distinctColours(ids: string[]): Map<string, CSSProperties> {
  const out = new Map<string, CSSProperties>()
  const bands = [86, 79, 92]
  ids.forEach((id, i) => {
    if (out.has(id)) return
    const n = out.size
    const hue = Math.round((n * 137.508) % 360 * 10) / 10
    const light = bands[n % bands.length]
    out.set(id, {
      backgroundColor: `hsl(${hue} 75% ${light}%)`,
      color: `hsl(${hue} 70% 18%)`,
      boxShadow: `inset 0 0 0 1px hsl(${hue} 60% 50%)`,
    })
    void i
  })
  return out
}
