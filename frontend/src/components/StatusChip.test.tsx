import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DecisionChip, StatusChip } from './StatusChip'

describe('StatusChip', () => {
  it('always renders the status as text, not only colour', () => {
    render(<StatusChip status="needs_review" />)
    expect(screen.getByText('Needs Review')).toBeInTheDocument()
  })

  it('uses the workflow label for terminal states', () => {
    render(<StatusChip status="completed" labels={{ completed: 'Implemented' }} />)
    expect(screen.getByText('Implemented')).toBeInTheDocument()
  })

  it('renders decisions as Salt status text', () => {
    render(<DecisionChip decision="accept" />)
    expect(screen.getByText('Accepted')).toBeInTheDocument()
  })
})
