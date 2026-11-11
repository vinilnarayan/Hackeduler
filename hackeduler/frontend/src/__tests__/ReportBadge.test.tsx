import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReportBadge } from '../components/ui'

describe('ReportBadge', () => {
  it('shows not shared', () => {
    render(<ReportBadge shared={false} />)
    expect(screen.getByText('Not shared')).toBeTruthy()
  })
  it('shows the report type when shared', () => {
    const { rerender } = render(<ReportBadge shared type="V1" />)
    expect(screen.getByText('Shared · V1 report')).toBeTruthy()
    rerender(<ReportBadge shared type="Met" />)
    expect(screen.getByText('Shared · Met report')).toBeTruthy()
  })
})
