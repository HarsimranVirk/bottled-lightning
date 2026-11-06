/** History table: standard filter row, rows, empty states and pagination. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { HistoryRow, WorkflowFieldView } from '../api'
import { EMPTY_HISTORY_FILTERS } from '../queries'
import { HistoryTable } from './HistoryTable'

const FIELDS: WorkflowFieldView[] = [
  {
    key: 'loan_amount',
    label: 'Loan Amount',
    valueType: 'amount',
    required: false,
    targets: ['cl_contract'],
  },
]

function row(
  key: string,
  status = 'ready',
  refs: HistoryRow['refs'] = [],
): HistoryRow {
  return {
    key,
    status,
    present: true,
    epoch: 1,
    recordUrl: null,
    approvedAt: '4/11/2026',
    reason: null,
    fields: {
      loan_amount: {
        extracted: '1300000',
        lastSynced: '1300000',
        proposed: null,
        applied: null,
        status: 'extracted',
      },
    },
    decision: { decision: 'accept', reason: null, at: '2026-11-04T18:20:00Z' },
    activeJob: null,
    refs,
  }
}

function props(overrides: Partial<Parameters<typeof HistoryTable>[0]> = {}) {
  return {
    rows: [
      row('Deviation-A', 'ready', [
        { kind: 'opportunity', name: 'Opportunity 1', url: 'https://e/opp' },
        { kind: 'collateral', name: 'CJID-0000280688', url: 'https://e/coll' },
      ]),
      row('Deviation-B', 'completed'),
    ],
    fields: FIELDS,
    terminalLabels: { completed: 'Implemented' },
    listUrl: 'https://example/list',
    filters: EMPTY_HISTORY_FILTERS,
    onFilters: vi.fn(),
    page: 1,
    size: 25,
    total: 2,
    onPage: vi.fn(),
    onSize: vi.fn(),
    loading: false,
    onOpen: vi.fn(),
    ...overrides,
  }
}

describe('HistoryTable', () => {
  it('renders the standard filter row for every column', () => {
    render(<HistoryTable {...props()} />)
    expect(screen.getByLabelText('Filter by deviation')).toBeInTheDocument()
    expect(screen.getByLabelText('Decided from')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by status')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by SF approval')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by Opportunity')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by CL contract')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by Collateral')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by LMS2 CL contract')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by LMS2 collateral')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by Loan Amount')).toBeInTheDocument()
  })

  it('labels status options with the workflow terminal wording', async () => {
    const user = userEvent.setup()
    render(<HistoryTable {...props()} />)
    await user.click(screen.getByLabelText('Filter by status values'))
    expect(screen.getByRole('option', { name: 'Implemented' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Ready' })).toBeInTheDocument()
  })

  it('renders object links and a dash for a missing kind', () => {
    render(<HistoryTable {...props()} />)
    expect(
      screen.getByRole('link', { name: /Opportunity 1/ }),
    ).toHaveAttribute('href', 'https://e/opp')
    expect(
      screen.getByRole('link', { name: /CJID-0000280688/ }),
    ).toHaveAttribute('href', 'https://e/coll')
    // Row A misses three kinds; row B misses all five.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(8)
  })

  it('filters on a linked object name', async () => {
    const user = userEvent.setup()
    const onFilters = vi.fn()
    render(<HistoryTable {...props({ onFilters })} />)

    await user.type(screen.getByLabelText('Filter by Opportunity'), 'O')
    expect(onFilters).toHaveBeenLastCalledWith({
      ...EMPTY_HISTORY_FILTERS,
      refText: { opportunity: 'O' },
    })
  })

  it('updates the text filter and the exact-value selection', async () => {
    const user = userEvent.setup()
    const onFilters = vi.fn()
    render(<HistoryTable {...props({ onFilters })} />)

    await user.type(screen.getByLabelText('Filter by deviation'), 'A')
    expect(onFilters).toHaveBeenLastCalledWith({
      ...EMPTY_HISTORY_FILTERS,
      key: 'A',
    })

    await user.click(screen.getByLabelText('Filter by status values'))
    await user.click(screen.getByRole('option', { name: 'Ready' }))
    expect(onFilters).toHaveBeenLastCalledWith({
      ...EMPTY_HISTORY_FILTERS,
      statuses: ['ready'],
    })
  })

  it('shows the filtered empty state and clears filters', async () => {
    const user = userEvent.setup()
    const onFilters = vi.fn()
    render(
      <HistoryTable
        {...props({
          rows: [],
          total: 0,
          filters: { ...EMPTY_HISTORY_FILTERS, statuses: ['ready'] },
          onFilters,
        })}
      />,
    )
    expect(
      screen.getByText('No approved deviations match these filters.'),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onFilters).toHaveBeenCalledWith(EMPTY_HISTORY_FILTERS)
  })
})
