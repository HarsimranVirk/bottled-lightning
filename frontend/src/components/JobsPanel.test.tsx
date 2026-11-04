/** Jobs table: per-column filters, sortable headers, pagination and the log panel. */

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { JobView } from '../api'
import type { JobFilters } from '../queries'
import { JobsPanel } from './JobsPanel'

const FILTERS: JobFilters = {
  id: '',
  status: '',
  kind: '',
  phase: '',
  item: '',
  error: '',
  startedAfter: '',
  startedBefore: '',
  durationMinS: '',
  durationMaxS: '',
}

function job(id: number, overrides: Partial<JobView> = {}): JobView {
  return {
    id,
    workflow: 'deviations_z02',
    item: 'Deviation-03112026-486382',
    kind: 'extract',
    status: 'succeeded',
    phase: 'extract',
    attempts: 1,
    leaseOwner: null,
    createdAt: '2026-11-04T10:00:00Z',
    startedAt: '2026-11-04T10:00:01Z',
    finishedAt: '2026-11-04T10:00:05Z',
    durationMs: 4200,
    error: null,
    ...overrides,
  }
}

function props(overrides: Partial<Parameters<typeof JobsPanel>[0]> = {}) {
  return {
    jobs: [job(12), job(11, { status: 'failed', error: 'LeaseHeld: nope', durationMs: null, startedAt: null })],
    total: 2,
    filters: FILTERS,
    onFilters: vi.fn(),
    sort: 'id',
    order: 'desc' as const,
    onSort: vi.fn(),
    page: 1,
    size: 25,
    onPage: vi.fn(),
    onSize: vi.fn(),
    selected: null,
    logs: undefined,
    loadingLogs: false,
    onSelect: vi.fn(),
    loading: false,
    ...overrides,
  }
}

describe('JobsPanel', () => {
  it('renders the table with duration and started time', () => {
    render(<JobsPanel {...props()} />)
    expect(screen.getByText('#12')).toBeInTheDocument()
    expect(screen.getByText('4.2s')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getByText('LeaseHeld: nope')).toBeInTheDocument()
    expect(screen.getByText('1–2 of 2')).toBeInTheDocument()
  })

  it('updates a filter on every input', () => {
    const onFilters = vi.fn()
    render(<JobsPanel {...props({ onFilters })} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Filter by job id' }), {
      target: { value: '42' },
    })
    expect(onFilters).toHaveBeenCalledWith({ ...FILTERS, id: '42' })
  })

  it('sorts from a column header', async () => {
    const user = userEvent.setup()
    const onSort = vi.fn()
    render(<JobsPanel {...props({ onSort, sort: 'id', order: 'desc' })} />)
    await user.click(screen.getByRole('button', { name: /Duration/ }))
    expect(onSort).toHaveBeenCalledWith('duration')
    expect(screen.getByRole('columnheader', { name: /ID/ })).toHaveAttribute('aria-sort', 'descending')
  })

  it('pages and changes the page size', async () => {
    const user = userEvent.setup()
    const onPage = vi.fn()
    const onSize = vi.fn()
    render(
      <JobsPanel {...props({ total: 60, page: 2, size: 25, onPage, onSize })} />,
    )
    expect(screen.getByText('26–50 of 60')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Previous' }))
    expect(onPage).toHaveBeenCalledWith(1)
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(onPage).toHaveBeenCalledWith(3)
  })

  it('selects a row and shows its logs', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(
      <JobsPanel
        {...props({ onSelect, selected: 11 })}
        logs={{ job: job(11), logs: ['extract start: …', 'failed: LeaseHeld'] }}
      />,
    )
    await user.click(screen.getByText('#12'))
    expect(onSelect).toHaveBeenCalledWith(12)
    expect(screen.getByText('Job #11')).toBeInTheDocument()
    expect(screen.getByText(/failed: LeaseHeld/)).toBeInTheDocument()
  })

  it('explains a filtered-empty table and clears the filters', async () => {
    const user = userEvent.setup()
    const onFilters = vi.fn()
    render(
      <JobsPanel {...props({ jobs: [], total: 0, filters: { ...FILTERS, status: 'failed' }, onFilters })} />,
    )
    expect(screen.getByText('No jobs match these filters.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onFilters).toHaveBeenCalledWith(FILTERS)
  })
})
