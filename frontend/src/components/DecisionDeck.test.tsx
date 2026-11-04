/** Review deck behaviour: legacy card fields, tallies, buttons, keys and replay. */

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
    detail: null,
    tally: { accept: 1, skip: 2, pending: 2 },
    error: null,
    announcement: '',
    enabled: true,
    onDecide: vi.fn(async () => true),
    onReplay: vi.fn(),
    replaying: false,
    onOpen: vi.fn(),
    onRefresh: vi.fn(),
    refreshing: false,
    ...overrides,
  }
}

describe('DecisionDeck', () => {
  it('renders the legacy tallies and the top card values', () => {
    render(<DecisionDeck {...deckProps()} />)
    expect(screen.getByText('1 accepted')).toBeInTheDocument()
    expect(screen.getByText('2 skipped')).toBeInTheDocument()
    expect(screen.getByText('2 to review')).toBeInTheDocument()
    expect(screen.getByText('Deviation-1-1')).toBeInTheDocument()
    expect(screen.getAllByDisplayValue('13,00,000').length).toBeGreaterThan(0)
    expect(screen.getByText('next up: Deviation-2-2')).toBeInTheDocument()
  })

  it('accepts with the corrected field values', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn(async () => true)
    render(<DecisionDeck {...deckProps({ onDecide })} />)

    const amount = screen.getByLabelText('Loan Amount')
    await user.clear(amount)
    await user.type(amount, '1500000')
    await user.click(screen.getByRole('button', { name: /Accept/ }))

    expect(onDecide).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'Deviation-1-1' }),
      'accept',
      expect.objectContaining({ loan_amount: '15,00,000', tenure: '240' }),
    )
  })

  it('skips with the Skip button and with ArrowLeft', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn(async () => true)
    render(<DecisionDeck {...deckProps({ onDecide })} />)

    await user.click(screen.getByRole('button', { name: /Skip/ }))
    expect(onDecide).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 'Deviation-1-1' }),
      'reject',
      {},
    )

    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(onDecide).toHaveBeenLastCalledWith(
      expect.objectContaining({ key: 'Deviation-1-1' }),
      'reject',
      {},
    )
  })

  it('accepts with ArrowRight', () => {
    const onDecide = vi.fn(async () => true)
    render(<DecisionDeck {...deckProps({ onDecide })} />)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(onDecide).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'Deviation-1-1' }),
      'accept',
      expect.objectContaining({ loan_amount: '13,00,000' }),
    )
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
    expect(screen.getByRole('button', { name: /Accept/ })).toBeEnabled()
  })

  it('keeps the card when a decision fails', () => {
    render(<DecisionDeck {...deckProps({ error: 'item is submitting and not decidable' })} />)
    expect(screen.getByText('item is submitting and not decidable')).toBeInTheDocument()
    expect(screen.getByText('Deviation-1-1')).toBeInTheDocument()
  })

  it('shows the completion card and replays skipped decisions', async () => {
    const user = userEvent.setup()
    const onReplay = vi.fn()
    render(
      <DecisionDeck
        {...deckProps({ rows: [], tally: { accept: 4, skip: 2, pending: 0 }, onReplay })}
      />,
    )
    expect(screen.getByText('Deck complete 🎉')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Replay skipped \(2\)/ }))
    expect(onReplay).toHaveBeenCalled()
  })

  it('ignores keyboard decisions while disabled (detail panel open)', () => {
    const onDecide = vi.fn(async () => true)
    render(<DecisionDeck {...deckProps({ onDecide, enabled: false })} />)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(onDecide).not.toHaveBeenCalled()
  })
})
