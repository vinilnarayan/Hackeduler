import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import ManualAllocation from '../pages/admin/ManualAllocation'

const acts = [
  { id: 'a1', name: 'XBOW', is_active: true, base_duration_days: null, requires_resource: false, description: '', yearly_limit: 10 },
  { id: 'a2', name: 'Others', is_active: true, base_duration_days: 1, requires_resource: true, description: '', yearly_limit: null },
]

describe('Manual allocation: yearly balance', () => {
  beforeEach(() => {
    api.get.mockReset(); api.post.mockReset()
    api.get.mockImplementation((u: string) => Promise.resolve(u.includes('/quota') ? { quota: { year: Number(u.split('year=')[1]), limit: 10, used: 3, remaining: 7 } } : u.includes('activity-types') ? acts : []))
    api.post.mockResolvedValue({ available: true, issues: [], message: '' })
  })

  it('shows the balance for the start year, only for limited activities', async () => {
    render(<MemoryRouter><ManualAllocation /></MemoryRouter>)
    const sel = await screen.findByLabelText(/Activity type/)
    fireEvent.change(sel, { target: { value: 'a1' } })
    expect((await screen.findByTestId('yearly-balance')).textContent).toMatch(/Balance for \d{4}:\s*7\s*of 10/)
    fireEvent.change(screen.getByLabelText(/Date \(optional\)/), { target: { value: '2027-03-01' } })
    await vi.waitFor(() => expect(screen.getByTestId('yearly-balance').textContent).toMatch(/Balance for 2027/))
    fireEvent.change(sel, { target: { value: 'a2' } })
    await vi.waitFor(() => expect(screen.queryByTestId('yearly-balance')).toBeNull())
  })
})
