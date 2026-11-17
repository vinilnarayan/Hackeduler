import { fireEvent, render, screen } from '@testing-library/react'
import { SortTh, useSort } from '../components/SortTh'

type Row = { name: string; n: number | null; when: string }
const ROWS: Row[] = [
  { name: 'beta', n: 10, when: '2027-03-02' },
  { name: 'Alpha', n: 2, when: '2027-03-09' },
  { name: 'gamma', n: null, when: '2027-03-01' },
  { name: 'item 10', n: 5, when: '2027-03-05' },
]

function Table() {
  const t = useSort(ROWS, { name: (r) => r.name, n: (r) => r.n, when: (r) => r.when })
  return (
    <table>
      <thead><tr><SortTh label="Name" k="name" sort={t.sort} onToggle={t.toggle} /><SortTh label="Count" k="n" sort={t.sort} onToggle={t.toggle} /></tr></thead>
      <tbody>{t.sorted.map((r) => <tr key={r.name}><td>{r.name}</td></tr>)}</tbody>
    </table>
  )
}
const names = () => screen.getAllByRole('row').slice(1).map((r) => r.textContent)

describe('sortable table headers', () => {
  it('sorts ascending, then descending, then back to the original order', () => {
    render(<Table />)
    expect(names()).toEqual(['beta', 'Alpha', 'gamma', 'item 10'])
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Name' }))
    expect(names()).toEqual(['Alpha', 'beta', 'gamma', 'item 10'])                 // case-insensitive
    expect(screen.getByRole('columnheader', { name: /Name/ }).getAttribute('aria-sort')).toBe('ascending')
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Name' }))
    expect(names()).toEqual(['item 10', 'gamma', 'beta', 'Alpha'])
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Name' }))
    expect(names()).toEqual(['beta', 'Alpha', 'gamma', 'item 10'])
  })

  it('sorts numbers numerically and keeps empty values last in both directions', () => {
    render(<Table />)
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Count' }))
    expect(names()).toEqual(['Alpha', 'item 10', 'beta', 'gamma'])                 // 2, 5, 10, empty
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Count' }))
    expect(names()).toEqual(['beta', 'item 10', 'Alpha', 'gamma'])                 // 10, 5, 2, empty
  })

  it('switching column starts ascending again', () => {
    render(<Table />)
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Name' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Name' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Count' }))
    expect(names()[0]).toBe('Alpha')
  })
})
