/** Dev DB explorer page: table picker, SQL editor and query dispatch. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DevDbPage } from './DevDbPage'

interface TableState {
  data: { tables: { name: string; rows: number; columns: string[] }[] }
  isPending: boolean
  isError: boolean
  error: Error | null
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
  return {
    tables,
    query: {
      data: undefined,
      isPending: false,
      error: null,
      mutate: vi.fn(),
    },
    exporter: {
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
}))

describe('DevDbPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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

  it('shows the disabled hint when the backend rejects the table list', () => {
    mocks.tables.isError = true
    mocks.tables.error = new Error('dev tools are disabled')
    renderPage()
    expect(screen.getByText(/Dev tools are disabled/)).toBeInTheDocument()
    mocks.tables.isError = false
    mocks.tables.error = null
  })
})
