import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import Bookings from '../pages/admin/Bookings'

const listCalls = () => api.get.mock.calls.map((c) => c[0] as string).filter((u) => u.startsWith('/api/admin/bookings?'))

describe('Admin bookings: PCI and report filters', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/bookings?') ? { total: 0, items: [] } : []))
  })

  it('sends the PCI filter', async () => {
    render(<MemoryRouter><Bookings /></MemoryRouter>)
    fireEvent.change(await screen.findByLabelText('PCI DSS scope'), { target: { value: 'true' } })
    await vi.waitFor(() => expect(listCalls().some((u) => u.includes('pci=true'))).toBe(true))
  })

  it.each([
    ['shared', 'report_shared=true', false],
    ['not_shared', 'report_shared=false', false],
    ['V1', 'report_shared=true', true],
  ])('maps the report choice %s to API parameters', async (choice, expected, withType) => {
    render(<MemoryRouter><Bookings /></MemoryRouter>)
    fireEvent.change(await screen.findByLabelText('Report'), { target: { value: choice } })
    await vi.waitFor(() => expect(listCalls().some((u) => u.includes(expected) && u.includes('report_type=V1') === withType)).toBe(true))
  })
})
