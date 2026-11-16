import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ ...api, ApiError: class extends Error {}, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))

import NewBooking from '../pages/requester/NewBooking'

const alpha = { id: 'p1', name: 'Alpha', is_primary: true, implementations: [{ id: 'i1', name: 'A-impl' }], default_implementation_id: 'i1' }
const beta = { id: 'p2', name: 'Beta', is_primary: false, implementations: [{ id: 'i2', name: 'B-impl' }], default_implementation_id: null }
const mine = (products: any[]) => ({ product: { id: 'p1', name: 'Alpha' }, implementations: alpha.implementations, default_implementation_id: 'i1', products })

const setup = (products: any[]) => {
  api.get.mockImplementation((url: string) => Promise.resolve(url.includes('/api/me/implementations') ? mine(products) : []))
  render(<MemoryRouter><NewBooking /></MemoryRouter>)
}

describe('New booking: products', () => {
  beforeEach(() => { api.get.mockReset() })

  it('lets a requester with several products choose one, and the implementations follow it', async () => {
    setup([alpha, beta])
    const product = (await screen.findByLabelText(/^Product/)) as HTMLSelectElement
    expect(Array.from(product.options).map((o) => o.text)).toEqual(['Alpha', 'Beta'])
    expect(Array.from((screen.getByLabelText('Implementation') as HTMLSelectElement).options).map((o) => o.text)).toEqual(['— Not specific —', 'A-impl'])
    fireEvent.change(product, { target: { value: 'p2' } })
    expect(Array.from((screen.getByLabelText('Implementation') as HTMLSelectElement).options).map((o) => o.text)).toEqual(['— Not specific —', 'B-impl'])
    expect((screen.getByLabelText('Implementation') as HTMLSelectElement).value).toBe('')
  })

  it('shows no product picker for a single product', async () => {
    setup([alpha])
    await screen.findByLabelText('Implementation')
    expect(screen.queryByLabelText(/^Product/)).toBeNull()
  })
})
