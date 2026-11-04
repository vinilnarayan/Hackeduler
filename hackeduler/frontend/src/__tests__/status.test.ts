import { CELL_STYLE, STATUS_LABELS, cellExplanation } from '../lib/status'
import { qs } from '../api/client'

describe('status helpers', () => {
  it('has consistent labels', () => {
    expect(STATUS_LABELS.pending_approval).toBe('Pending Approval')
    expect(Object.keys(STATUS_LABELS)).toHaveLength(6)
  })
  it('maps required colour meanings', () => {
    expect(CELL_STYLE.available.label).toBe('Green')
    expect(CELL_STYLE.occupied.label).toBe('Red')
    expect(CELL_STYLE.limited.label).toBe('Yellow')
    expect(CELL_STYLE.reserved.label).toBe('Blue')
    expect(CELL_STYLE.non_working.label).toBe('Grey')
  })
  it('explains non-working causes without personal details', () => {
    expect(cellExplanation('non_working', 'weekend')).toMatch(/Weekend/)
    expect(cellExplanation('non_working', 'holiday', 'Diwali')).toBe('Organisation holiday: Diwali')
    expect(cellExplanation('non_working', 'leave')).toBe('Resource unavailable (leave)')
  })
  it('builds query strings skipping empty values', () => {
    expect(qs({ a: 1, b: '', c: null, d: 'x y' })).toBe('?a=1&d=x+y')
  })
})
