import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: { role: 'requester', full_name: 'Req One', email: 'r@x.y' }, logout: vi.fn() }) }))

import { Layout } from '../components/Layout'

describe('About / branding', () => {
  it('shows the credit and contact in the footer and in an About dialog, for any role', () => {
    render(<MemoryRouter><Layout /></MemoryRouter>)
    expect(screen.getAllByText(/Designed and developed by/).length).toBeGreaterThan(0)
    const mail = screen.getAllByRole('link', { name: 'OffSec_Team@ibsplc.com' })[0]
    expect(mail.getAttribute('href')).toBe('mailto:OffSec_Team@ibsplc.com')
    fireEvent.click(screen.getAllByRole('button', { name: /About/ })[0])
    expect(screen.getByRole('dialog')).toHaveTextContent('OffSec Team, InfoSec, IBS Group')
    expect(screen.getByRole('dialog')).toHaveTextContent('OffSec_Team@ibsplc.com')
  })

  it('uses the Hackeduler logo in the header', () => {
    const { container } = render(<MemoryRouter><Layout /></MemoryRouter>)
    expect(container.querySelector('img[src="/logo.png"]')).not.toBeNull()
  })
})
