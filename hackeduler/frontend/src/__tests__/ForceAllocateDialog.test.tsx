import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import type { OverrideDetails } from '../api/types'

const authState: { user: any } = { user: null }
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: authState.user }) }))

import { ForceAllocateDialog } from '../components/ForceAllocateDialog'

const details: OverrideDetails = {
  requires_force: true,
  warning: 'Warning: This allocation conflicts with an existing booking or resource restriction.',
  issues: [{ type: 'overlapping_booking', message: 'Overlap', dates: ['2027-03-03'] }],
  conflicting_bookings: [{ id: '550e8400-e29b-41d4-a716-446655440000', application_name: 'Portal', status: 'approved', start_date: '2027-03-01', end_date: '2027-03-10', poc_name: 'Jane', poc_email: 'j@x.com' }],
  plan: { resource_id: 'r', start_date: '2027-03-03', end_date: '2027-03-12', duration_days: 8, work_dates: [] },
}

describe('ForceAllocateDialog', () => {
  it('renders nothing for requesters', () => {
    authState.user = { role: 'requester' }
    const { container } = render(<ForceAllocateDialog open details={details} onClose={() => {}} onConfirm={async () => {}} />)
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByText(/Force Allocate/)).toBeNull()
  })

  it('requires reason and explicit confirmation for admins', async () => {
    authState.user = { role: 'admin' }
    const onConfirm = vi.fn(async () => {})
    render(<ForceAllocateDialog open details={details} onClose={() => {}} onConfirm={onConfirm} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Warning: This allocation conflicts')
    expect(screen.getByText('Portal')).toBeInTheDocument()
    const btn = screen.getByRole('button', { name: 'Force Allocate' })
    expect(btn).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Override reason/), { target: { value: 'CISO approved' } })
    expect(btn).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(btn).toBeEnabled()
    fireEvent.click(btn)
    expect(onConfirm).toHaveBeenCalledWith({ confirm: true, reason: 'CISO approved' })
  })
})
