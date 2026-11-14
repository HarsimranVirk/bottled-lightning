/** LMS2 approval audit table: links, status wording, reason and filters. */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { HistoryRow } from '../api'
import { EMPTY_HISTORY_FILTERS } from '../queries'
import { ApprovalHistoryTable } from './ApprovalHistoryTable'

const URL =
  'https://hffc.lightning.force.com/lightning/n/CL_Contract_Detail?c__loanId=LAI-1'
const TERMINAL_LABELS = { completed: 'Approved' }

function historyRow(): HistoryRow {
  return {
    key: 'LAI-1',
    status: 'completed',
    present: true,
    epoch: 1,
    recordUrl: URL,
    approvedAt: null,
    reason: 'approved',
    fields: {},
    decision: {
      decision: 'accept',
      reason: 'queued for approval',
      at: '2026-11-14T10:00:00Z',
    },
    activeJob: null,
    refs: [
      {
        kind: 'lms2_cl_contract',
        name: 'LAI-1',
        url: URL,
        state: 'found',
      },
    ],
  }
}

function props(
  overrides: Partial<Parameters<typeof ApprovalHistoryTable>[0]> = {},
) {
  return {
    rows: [historyRow()],
    total: 1,
    filters: EMPTY_HISTORY_FILTERS,
    onFilters: vi.fn(),
    page: 1,
    size: 25,
    onPage: vi.fn(),
    onSize: vi.fn(),
    loading: false,
    terminalLabels: TERMINAL_LABELS,
    ...overrides,
  }
}

describe('ApprovalHistoryTable', () => {
  it('shows the workflow terminal wording and the approval reason', () => {
    render(<ApprovalHistoryTable {...props()} />)
    expect(screen.getByText('Approved')).toBeInTheDocument()
    expect(screen.getByText('approved')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /LAI-1/ })).toHaveAttribute(
      'href',
      URL,
    )
  })

  it('offers the contract, requested-date and status filters', () => {
    render(<ApprovalHistoryTable {...props()} />)
    expect(
      screen.getByRole('combobox', { name: 'Filter by contract' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Requested from')).toBeInTheDocument()
    expect(
      screen.getByRole('combobox', { name: 'Filter by status' }),
    ).toBeInTheDocument()
  })
})
