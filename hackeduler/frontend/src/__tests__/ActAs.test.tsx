import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

const auth = vi.hoisted(() => ({ value: {} as any }))
vi.mock('../lib/auth', () => ({ useAuth: () => auth.value }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), get: vi.fn(async (u: string) => (u.includes('users') ? users : [])), validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))

import { Layout } from '../components/Layout'
import UsersPage from '../pages/admin/Users'

const mk = (o: any) => ({ is_active: true, has_password: true, products: [], extra_product_ids: [], ...o })
const users = [mk({ id: 'a1', email: 'admin@x.com', full_name: 'Boss Admin', role: 'admin' }), mk({ id: 'r1', email: 'req@x.com', full_name: 'Req One', role: 'requester' }),
  mk({ id: 'e1', email: 'eng@x.com', full_name: 'Eng One', role: 'resource' }), mk({ id: 'r2', email: 'off@x.com', full_name: 'Off User', role: 'requester', is_active: false })]

describe('Act as', () => {
  it('offers Act as for active non-admin users only, and starts it', async () => {
    const actAs = vi.fn().mockResolvedValue(undefined)
    auth.value = { user: { id: 'a1', role: 'admin', full_name: 'Boss Admin' }, actAs, acting: null }
    render(<MemoryRouter><UsersPage /></MemoryRouter>)
    await screen.findByText('Req One')
    const btns = screen.getAllByRole('button', { name: 'Act as' })
    expect(btns.length).toBe(2)                         // Req One + Eng One (not the admin, not the disabled user)
    fireEvent.click(btns[0])
    await waitFor(() => expect(actAs).toHaveBeenCalledWith('r1'))
  })

  it('shows the banner and exits', () => {
    const exitActing = vi.fn()
    auth.value = { user: { id: 'r1', role: 'requester', full_name: 'Req One', email: 'req@x.com' }, logout: vi.fn(), exitActing, acting: { admin_name: 'Boss Admin', admin_email: 'admin@x.com', expires_at: '2030-01-01T00:00:00Z' } }
    render(<MemoryRouter><Layout /></MemoryRouter>)
    expect(screen.getByRole('status').textContent).toContain('acting as Req One')
    fireEvent.click(screen.getByText('Exit act as'))
    expect(exitActing).toHaveBeenCalled()
  })
})
