/** Review deck behaviour: buttons, keys, reason, undo and the empty/error states. */

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ItemRow, WorkflowFieldView } from '../api'
import { DecisionDeck } from './DecisionDeck'

const FIELDS: WorkflowFieldView[] = [
  { key: 'loan_amount', label: 'Loan Amount', valueType: 'amount', required: false, targets: [] },
  { key: 'tenure', label: 'Tenure', valueType: 'months', required: false, targets: [] },
]

function row(key: string, overrides: Partial<ItemRow> = {}): ItemRow {
  return {
    key,
    status: 'ready',
    present: true,
    epoch: 1,
    recordUrl: null,
    approvedAt: '4/11/2026 6:46 pm',
    reason: null,
    fields: {
      loan_amount: {
        extracted: '13,00,000',
        lastSynced: '13,00,000',
        proposed: null,
        applied: null,
        status: 'extracted',
      },
      tenure: {
        extracted: '240',
        lastSynced: '240',
        proposed: null,
        applied: null,
        status: 'extracted',
      },
    },
    decision: null,
    activeJob: null,
    ...overrides,
  }
}

function deckProps(overrides: Partial<Parameters<typeof DecisionDeck>[0]> = {}) {
  return {
    rows: [row('Deviation-1-1'), row('Deviation-2-2')],
    fields: FIELDS,
    terminalLabels: {},
    busyKey: null,
    undoBusy: false,
    canUndo: false,
    error: null,
    announcement: '',
    enabled: true,
    onDecide: vi.fn(),
    onUndo: vi.fn(),
    onOpen: vi.fn(),
    onShowList: vi.fn(),
    onReload: vi.fn(),
    reloading: false,
    ...overrides,
  }
}

describe('DecisionDeck', () => {
  it('shows the top card and the remaining count', () => {
    render(<DecisionDeck {...deckProps()} />)
    expect(screen.getByText('2 to review')).toBeInTheDocument()
    expect(screen.getByText('Deviation-1-1')).toBeInTheDocument()
    expect(screen.getAllByText('13,00,000').length).toBeGreaterThan(0)
  })

  it('accepts with the button and rejects with the other button', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    render(<DecisionDeck {...deckProps({ onDecide })} />)

    await user.click(screen.getByRole('button', { name: 'Accept Deviation-1-1' }))
    expect(onDecide).toHaveBeenCalledWith('Deviation-1-1', 'accept')

    await user.click(screen.getByRole('button', { name: 'Reject Deviation-1-1' }))
    await user.click(screen.getByRole('button', { name: 'Reject without reason' }))
    expect(onDecide).toHaveBeenLastCalledWith('Deviation-1-1', 'reject')
  })

  it('accepts with ArrowRight and rejects with ArrowLeft', () => {
    const onDecide = vi.fn()
    render(<DecisionDeck {...deckProps({ onDecide })} />)

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(onDecide).toHaveBeenCalledWith('Deviation-1-1', 'accept')

    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(onDecide).toHaveBeenCalledWith('Deviation-1-1', 'reject')
  })

  it('collects an optional reason before rejecting', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn()
    render(<DecisionDeck {...deckProps({ onDecide })} />)

    await user.click(screen.getByRole('button', { name: 'Reject Deviation-1-1' }))
    const input = screen.getByLabelText('Reject reason')
    await user.type(input, 'EMI mismatch')
    await user.click(screen.getByRole('button', { name: 'Reject' }))
    expect(onDecide).toHaveBeenCalledWith('Deviation-1-1', 'reject', 'EMI mismatch')
  })

  it('undoes the last decision', async () => {
    const user = userEvent.setup()
    const onUndo = vi.fn()
    render(<DecisionDeck {...deckProps({ canUndo: true, onUndo })} />)
    await user.click(screen.getByRole('button', { name: 'Undo last' }))
    expect(onUndo).toHaveBeenCalled()
  })

  it('warns about missing values without blocking the decision', () => {
    const rows = [
      row('Deviation-1-1', {
        fields: {
          loan_amount: {
            extracted: null,
            lastSynced: null,
            proposed: null,
            applied: null,
            status: 'extracted',
          },
          tenure: {
            extracted: null,
            lastSynced: null,
            proposed: null,
            applied: null,
            status: 'extracted',
          },
        },
      }),
    ]
    render(<DecisionDeck {...deckProps({ rows })} />)
    expect(screen.getByText(/2 values are missing/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept Deviation-1-1' })).toBeEnabled()
  })

  it('keeps the card when a decision fails', () => {
    render(<DecisionDeck {...deckProps({ error: 'item is submitting and not decidable' })} />)
    expect(screen.getByRole('alert')).toHaveTextContent('item is submitting and not decidable')
    expect(screen.getByTestId('top-card')).toBeInTheDocument()
  })

  it('shows the empty state with links to the decided lists', async () => {
    const user = userEvent.setup()
    const onShowList = vi.fn()
    render(<DecisionDeck {...deckProps({ rows: [], onShowList })} />)
    expect(screen.getByText('All caught up')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'View accepted' }))
    expect(onShowList).toHaveBeenCalledWith('accept')
    await user.click(screen.getByRole('button', { name: 'View rejected' }))
    expect(onShowList).toHaveBeenCalledWith('reject')
  })

  it('ignores keyboard decisions while disabled (detail panel open)', () => {
    const onDecide = vi.fn()
    render(<DecisionDeck {...deckProps({ onDecide, enabled: false })} />)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(onDecide).not.toHaveBeenCalled()
  })
})
