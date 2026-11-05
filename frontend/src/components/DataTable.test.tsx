/** Shared table: columns, filters, pagination, resize persistence, reset and rows. */

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DataColumn } from './DataTable'
import { DataTable } from './DataTable'

interface Row {
  id: number
  name: string
}

const COLUMNS: DataColumn<Row>[] = [
  {
    id: 'id',
    label: 'ID',
    header: 'ID',
    width: 100,
    filter: <input aria-label="Filter by ID" />,
    cell: (row) => `#${row.id}`,
  },
  { id: 'name', label: 'Name', header: 'Name', width: 200, cell: (row) => row.name },
]

function props(overrides: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) {
  return {
    tableId: 'test',
    columns: COLUMNS,
    rows: [
      { id: 1, name: 'Alpha' },
      { id: 2, name: 'Beta' },
    ],
    rowKey: (row: Row) => String(row.id),
    pagination: {
      page: 1,
      size: 25,
      total: 2,
      onPage: vi.fn(),
      onSize: vi.fn(),
    },
    ...overrides,
  }
}

function storedWidths(): Record<string, number> | null {
  const raw = window.localStorage.getItem('sf.data-table.widths.v1.test')
  return raw === null ? null : (JSON.parse(raw) as Record<string, number>)
}

describe('DataTable', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('renders the header, the filter row, rows and pagination', () => {
    render(<DataTable {...props()} />)
    expect(screen.getByRole('columnheader', { name: /ID/ })).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by ID')).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('1–2 of 2')).toBeInTheDocument()
  })

  it('drags a column wider and persists the width', () => {
    render(<DataTable {...props()} />)
    const handle = screen.getByRole('separator', { name: 'Resize ID' })

    fireEvent.pointerDown(handle, { clientX: 100 })
    fireEvent.pointerMove(window, { clientX: 140 })
    fireEvent.pointerUp(window)

    expect(storedWidths()).toMatchObject({ id: 140 })
    expect(screen.getByRole('button', { name: 'Reset columns' })).toBeInTheDocument()
  })

  it('resizes with the keyboard', () => {
    render(<DataTable {...props()} />)
    const handle = screen.getByRole('separator', { name: 'Resize ID' })

    fireEvent.keyDown(handle, { key: 'ArrowRight' })

    expect(storedWidths()).toMatchObject({ id: 116 })
  })

  it('restores stored widths and resets them to the defaults', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem(
      'sf.data-table.widths.v1.test',
      JSON.stringify({ id: 300 }),
    )
    render(<DataTable {...props()} />)

    await user.click(screen.getByRole('button', { name: 'Reset columns' }))

    expect(storedWidths()).toBeNull()
    expect(
      screen.queryByRole('button', { name: 'Reset columns' }),
    ).not.toBeInTheDocument()
  })

  it('wires pagination to the caller', async () => {
    const user = userEvent.setup()
    const onPage = vi.fn()
    render(
      <DataTable
        {...props({
          pagination: {
            page: 1,
            size: 25,
            total: 60,
            onPage,
            onSize: vi.fn(),
          },
        })}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(onPage).toHaveBeenCalledWith(2)
  })

  it('opens a row by click and by keyboard', async () => {
    const user = userEvent.setup()
    const onRowClick = vi.fn()
    render(<DataTable {...props({ onRowClick })} />)

    await user.click(screen.getByText('Alpha'))
    expect(onRowClick).toHaveBeenLastCalledWith({ id: 1, name: 'Alpha' })

    fireEvent.keyDown(screen.getByText('Beta'), { key: 'Enter' })
    expect(onRowClick).toHaveBeenLastCalledWith({ id: 2, name: 'Beta' })
  })

  it('shows the empty state when there are no rows', () => {
    render(
      <DataTable
        {...props({ rows: [], empty: <p>Nothing here</p> })}
      />,
    )
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
  })
})
