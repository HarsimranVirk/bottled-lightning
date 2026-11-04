import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatusChip } from './StatusChip'

describe('StatusChip', () => {
  it('always renders the status as text, not only colour', () => {
    render(<StatusChip status="needs_review" />)
    expect(screen.getByText('Needs Review')).toBeInTheDocument()
    expect(screen.getByText('Needs Review').closest('.chip')).toHaveAttribute('data-tone', 'danger')
  })

  it('uses the workflow label for terminal states', () => {
    render(<StatusChip status="completed" labels={{ completed: 'Implemented' }} />)
    expect(screen.getByText('Implemented')).toBeInTheDocument()
  })
})
