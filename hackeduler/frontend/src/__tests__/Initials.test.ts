import { initials } from '../lib/dates'

describe('initials', () => {
  it('uses the first letter of every word, upper-case', () => {
    expect(initials('Vinil P Prabhakaran')).toBe('VPP')
    expect(initials('Abilash V L')).toBe('AVL')
    expect(initials('Sagar Raja')).toBe('SR')
    expect(initials('  anna-marie  o.connor ')).toBe('AMOC')
  })
  it('falls back when there is no name', () => {
    expect(initials('', 'R01')).toBe('R01')
    expect(initials(null, 'R02')).toBe('R02')
  })
})
