/** Dev DB explorer page: table picker, SQL editor, filters and pagination. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DevQueryView, PurgeResult } from '../api'
import { DevDbPage } from './DevDbPage'

interface TableState {
  data: { tables: { name: string; rows: number; columns: string[] }[] }
  isPending: boolean
  isError: boolean
  error: Error | null
}

interface QueryState {
  data: DevQueryView | undefined
  isPending: boolean
  error: Error | null
  mutate: ReturnType<typeof vi.fn>
}

const mocks = vi.hoisted(() => {
  const tables: TableState = {
    data: {
      tables: [
        { name: 'work_items', rows: 1, columns: ['item_key'] },
        { name: 'jobs', rows: 0, columns: ['id'] },
      ],
    },
    isPending: false,
    isError: false,
    error: null,
  }
  const query: QueryState = {
    data: undefined,
    isPending: false,
    error: null,
    mutate: vi.fn(),
  }
  return {
    tables,
    query,
    exporter: {
      isPending: false,
      error: null,
      mutateAsync: vi.fn(),
    },
    purge: {
      isPending: false,
      error: null,
      mutateAsync: vi.fn(),
    },
  }
})

vi.mock('../queries', () => ({
  useDevTables: () => mocks.tables,
  useDevQuery: () => mocks.query,
  useDevExport: () => mocks.exporter,
  useDevPurge: () => mocks.purge,
}))

function sampleRows(count: number): DevQueryView {
  return {
    columns: ['item_key', 'status'],
    rows: Array.from({ length: count }, (_, index) => [
      `Deviation-${index}`,
      index === 0 ? 'ready' : 'closed',
    ]),
    rowCount: count,
    truncated: false,
    durationMs: 1,
  }
}

describe('DevDbPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.tables.isError = false
    mocks.tables.error = null
    mocks.query.data = undefined
    mocks.query.error = null
  })

  function renderPage(): void {
    render(
      <MemoryRouter>
        <DevDbPage />
      </MemoryRouter>,
    )
  }

  it('lists tables and loads one into the editor', async () => {
    const user = userEvent.setup()
    renderPage()
    const table = screen.getByRole('button', { name: /work_items/ })
    await user.click(table)
    expect(screen.getByLabelText('SQL query')).toHaveValue(
      'SELECT * FROM "work_items" LIMIT 100;',
    )
  })

  it('runs the current SQL', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Run query' }))
    expect(mocks.query.mutate).toHaveBeenCalledWith({
      sql: 'SELECT * FROM work_items LIMIT 100;',
      limit: 500,
    })
  })

  it('filters every column and paginates the result', async () => {
    const user = userEvent.setup()
    mocks.query.data = sampleRows(30)
    renderPage()

    expect(screen.getByText('1–25 of 30')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Filter by status'), 'ready')
    expect(screen.getByText(/1 of 30 rows/)).toBeInTheDocument()
    expect(screen.getByText('Deviation-0')).toBeInTheDocument()
    expect(screen.queryByText('Deviation-1')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getByText('1–25 of 30')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('26–30 of 30')).toBeInTheDocument()
  })

  it('previews and confirms a current-data purge', async () => {
    const user = userEvent.setup()
    const preview: PurgeResult = {
      scope: 'current',
      cutoff: '2026-11-04T18:20:00Z',
      dryRun: true,
      deleted: { work_items: 2, work_item_fields: 5 },
      total: 7,
    }
    const done: PurgeResult = {
      ...preview,
      dryRun: false,
    }
    mocks.purge.mutateAsync.mockImplementation(
      ({ dryRun }: { dryRun: boolean }) =>
        Promise.resolve(dryRun ? preview : done),
    )
    renderPage()

    await user.click(screen.getByRole('button', { name: 'Purge current data' }))
    expect(await screen.findByText(/7 rows/)).toBeInTheDocument()
    expect(screen.getByText('work_item_fields')).toBeInTheDocument()

    const confirm = screen.getByRole('button', { name: 'Purge' })
    expect(confirm).toBeDisabled()
    await user.click(
      screen.getByRole('checkbox', {
        name: 'I understand this cannot be undone.',
      }),
    )
    expect(confirm).not.toBeDisabled()
    await user.click(confirm)

    expect(mocks.purge.mutateAsync).toHaveBeenLastCalledWith({
      scope: 'current',
      dryRun: false,
    })
    expect(
      await screen.findByText(/Purged 7 rows from current data/),
    ).toBeInTheDocument()
  })

  it('offers the historical purge separately', async () => {
    const user = userEvent.setup()
    mocks.purge.mutateAsync.mockResolvedValue({
      scope: 'history',
      cutoff: '2026-08-07T18:20:00Z',
      dryRun: true,
      deleted: { approved_deviations: 1 },
      total: 1,
    } satisfies PurgeResult)
    renderPage()

    await user.click(
      screen.getByRole('button', { name: 'Purge historical data' }),
    )
    expect(
      await screen.findByText(/accepted more than 90 days ago/),
    ).toBeInTheDocument()
    expect(mocks.purge.mutateAsync).toHaveBeenCalledWith({
      scope: 'history',
      dryRun: true,
    })
  })

  it('shows the disabled hint when the backend rejects the table list', () => {
    mocks.tables.isError = true
    mocks.tables.error = new Error('dev tools are disabled')
    renderPage()
    expect(screen.getByText(/Dev tools are disabled/)).toBeInTheDocument()
  })
})
