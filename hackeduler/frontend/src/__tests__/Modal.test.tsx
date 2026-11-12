import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Modal } from '../components/ui'

function Demo({ onClose }: { onClose: () => void }) {
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  return (
    <Modal open onClose={() => onClose()} title="Demo">
      <input aria-label="first" value={a} onChange={(e) => setA(e.target.value)} />
      <input aria-label="second" value={b} onChange={(e) => setB(e.target.value)} />
    </Modal>
  )
}

describe('Modal focus', () => {
  it('does not steal focus back to the first field while typing', async () => {
    const onClose = vi.fn()
    render(<Demo onClose={onClose} />)
    await new Promise((r) => setTimeout(r, 10))
    expect(document.activeElement).toBe(screen.getByLabelText('first'))   // focused once on open
    const second = screen.getByLabelText('second') as HTMLInputElement
    second.focus()
    for (const ch of 'abc') {
      fireEvent.change(second, { target: { value: second.value + ch } })
      await new Promise((r) => setTimeout(r, 10))
    }
    expect(document.activeElement).toBe(second)
  })
  it('still closes on Escape', () => {
    const onClose = vi.fn()
    render(<Demo onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
