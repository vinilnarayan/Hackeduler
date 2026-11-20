import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'u1', name: 'Admin', role: 'admin' } }) }))

import Products from '../pages/admin/Products'

const products = [{ id: 'p1', name: 'Alpha', description: null, is_active: true, tags: ['Payments', 'Core'], users: 0, bookings: 0,
  implementations: [{ id: 'i1', product_id: 'p1', name: 'Cloud', description: null, is_active: true, tags: ['SaaS'], users: 0, bookings: 0 }] }]

describe('Products: tags', () => {
  beforeEach(() => { Object.values(api).forEach((f) => f.mockReset()); api.get.mockResolvedValue(products); api.patch.mockResolvedValue({}); api.post.mockResolvedValue({}) })

  it('shows tags and saves edited tags', async () => {
    render(<MemoryRouter><Products /></MemoryRouter>)
    expect(await screen.findByText('Payments')).toBeTruthy()
    expect(screen.getByText('Core')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const box = await screen.findByPlaceholderText(/Type a tag/).catch(() => null)
    const input = (box ?? document.getElementById('pr-t')) as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Cards, payments' } })         // comma adds; case-insensitive duplicate ignored
    fireEvent.click(screen.getByLabelText('Remove tag Core'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(api.patch.mock.calls[0][0]).toBe('/api/admin/products/p1')
    expect(api.patch.mock.calls[0][1].tags).toEqual(['Payments', 'Cards'])
  })
})
