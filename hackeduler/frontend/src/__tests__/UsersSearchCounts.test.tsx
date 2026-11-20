import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', async (orig) => ({ ...(await orig<typeof import('../api/client')>()), ...api, validationMessage: (e: any) => String(e?.message ?? e) }))
vi.mock('../lib/toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { id: 'me', role: 'admin' } }) }))

import Users from '../pages/admin/Users'

const base = { is_active: true, has_password: true, sso_provider_id: null, deleted_at: null, last_login_at: null, last_login_method: null, product_id: null, product_name: null, implementation_name: null, resource_name: null, extra_product_ids: [], products: [] }
const users = [
  { ...base, id: 'me', full_name: 'Alice Admin', email: 'alice@x.com', role: 'admin' },
  { ...base, id: '2', full_name: 'Bob Req', email: 'bob@x.com', role: 'requester', sso_provider_id: 's1', sso_provider_name: 'Entra', has_password: false },
  { ...base, id: '3', full_name: 'Carol Eng', email: 'carol@x.com', role: 'resource', resource_name: 'Res-1', has_password: false, is_active: false },
]

describe('Admin users: counts and search', () => {
  beforeEach(() => { api.get.mockReset(); api.get.mockImplementation((u: string) => Promise.resolve(u.startsWith('/api/admin/users') ? users : [])) })

  it('shows role, sign-in and status counts', async () => {
    render(<Users />)
    await screen.findByText('Alice Admin')
    const t = screen.getByTestId('user-counts').textContent!.replace(/\s+/g, ' ')
    expect(t).toMatch(/3 users/)
    expect(t).toMatch(/Admin 1 · Requester 1 · Resource 1/)
    expect(t).toMatch(/SSO 1 · Password 1 · SSO \(not yet signed in\) 1/)
    expect(t).toMatch(/Active 2 · Disabled 1/)
  })

  it('searches every column and updates the counts', async () => {
    render(<Users />)
    await screen.findByText('Alice Admin')
    const box = screen.getByLabelText('Search users')
    fireEvent.change(box, { target: { value: 'entra' } })      // sign-in provider
    expect(screen.queryByText('Alice Admin')).toBeNull(); expect(screen.getByText('Bob Req')).toBeTruthy()
    expect(screen.getByTestId('user-counts').textContent).toMatch(/1 user of 3/)
    fireEvent.change(box, { target: { value: 'res-1' } })      // resource name
    expect(screen.getByText('Carol Eng')).toBeTruthy(); expect(screen.queryByText('Bob Req')).toBeNull()
    fireEvent.change(box, { target: { value: 'disabled' } })   // status
    expect(screen.getByText('Carol Eng')).toBeTruthy(); expect(screen.queryByText('Alice Admin')).toBeNull()
    fireEvent.change(box, { target: { value: 'ALICE x.com' } }) // case-insensitive, multi-word
    expect(screen.getByText('Alice Admin')).toBeTruthy(); expect(screen.queryByText('Bob Req')).toBeNull()
    fireEvent.change(box, { target: { value: 'zzz' } })
    expect(screen.getByText('No users match your search')).toBeTruthy()
  })
})
