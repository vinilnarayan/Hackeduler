import { distinctColours } from '../lib/colours'

describe('distinctColours', () => {
  it('gives every id its own colour, however many there are', () => {
    const ids = Array.from({ length: 300 }, (_, i) => `b${i}`)
    const m = distinctColours(ids)
    expect(m.size).toBe(300)
    expect(new Set([...m.values()].map((v) => v.backgroundColor)).size).toBe(300)
  })
  it('is stable for the same order and ignores duplicate ids', () => {
    const a = distinctColours(['x', 'y', 'x', 'z'])
    expect(a.size).toBe(3)
    expect(a.get('x')).toEqual(distinctColours(['x', 'y', 'z']).get('x'))
    expect(a.get('x')!.backgroundColor).not.toBe(a.get('y')!.backgroundColor)
  })
})
