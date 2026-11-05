/**
 * One table implementation for every screen: columns, filter row, pagination and
 * resizable persisted widths (FR-9.20–FR-9.24).
 *
 * Callers describe columns declaratively; this component owns the markup, the width
 * state and the horizontal scroll container. Salt DS has no resize API, so widths are
 * applied through a `<colgroup>` with `table-layout: fixed` — the only way to keep the
 * header row, the filter row and the body aligned.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { JSX, ReactNode } from 'react'
import {
  Button,
  FlexLayout,
  Spinner,
  StackLayout,
  Table,
  TableContainer,
  TBody,
  TD,
  Text,
  TH,
  THead,
  TR,
} from '@salt-ds/core'

import { Pagination } from './Pagination'

/** One column: header content, filter control and row cell. */
export interface DataColumn<Row> {
  /** Stable id; also the width-storage key. */
  id: string
  /** Human label used by the resize control for screen readers. */
  label?: string
  header: ReactNode
  cell: (row: Row) => ReactNode
  filter?: ReactNode
  /** Default width in px. Omitted columns share the remaining space. */
  width?: number
  /** Resize floor; defaults to 80. */
  minWidth?: number
  align?: 'left' | 'right'
  /** Responsive hiding class (e.g. `history-values`, `job-col-phase`). */
  className?: string
  /** Sort state for a sortable header. */
  ariaSort?: 'ascending' | 'descending' | 'none'
}

interface DataTableProps<Row> {
  /** Width-storage key; changing it resets the columns to their defaults. */
  tableId: string
  columns: DataColumn<Row>[]
  rows: Row[]
  rowKey: (row: Row, index: number) => string
  onRowClick?: (row: Row) => void
  selectedKey?: string | null
  zebra?: boolean
  loading?: boolean
  empty?: ReactNode
  pagination: {
    page: number
    size: number
    total: number
    onPage: (page: number) => void
    onSize: (size: number) => void
  }
}

const STORAGE_PREFIX = 'sf.data-table.widths.v1.'
const MIN_WIDTH = 80
const MAX_WIDTH = 2000
const KEYBOARD_STEP = 16

function clampWidth(value: number): number {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(value)))
}

function storageKey(tableId: string): string {
  return `${STORAGE_PREFIX}${tableId}`
}

/** Read persisted widths, discarding anything malformed or out of range. */
function loadWidths(tableId: string): Record<string, number> {
  try {
    const raw = window.localStorage.getItem(storageKey(tableId))
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return {}
    const widths: Record<string, number> = {}
    for (const [id, value] of Object.entries(parsed)) {
      if (typeof value === 'number' && Number.isFinite(value)) {
        widths[id] = clampWidth(value)
      }
    }
    return widths
  } catch {
    return {}
  }
}

function saveWidths(tableId: string, widths: Record<string, number>): void {
  try {
    window.localStorage.setItem(storageKey(tableId), JSON.stringify(widths))
  } catch {
    // Storage can be unavailable or full; widths then last for this session only.
  }
}

function clearWidths(tableId: string): void {
  try {
    window.localStorage.removeItem(storageKey(tableId))
  } catch {
    // Nothing to clear.
  }
}

/** Defaults declared by the columns, keyed by column id. */
function defaultWidths<Row>(columns: DataColumn<Row>[]): Record<string, number> {
  const widths: Record<string, number> = {}
  for (const column of columns) {
    if (column.width !== undefined) widths[column.id] = column.width
  }
  return widths
}

export function DataTable<Row>({
  tableId,
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  zebra = false,
  loading = false,
  empty,
  pagination,
}: DataTableProps<Row>): JSX.Element {
  const defaults = useMemo(() => defaultWidths(columns), [columns])
  const [widths, setWidths] = useState<Record<string, number>>(() => ({
    ...defaultWidths(columns),
    ...loadWidths(tableId),
  }))
  const widthsRef = useRef(widths)
  const [drag, setDrag] = useState<{
    id: string
    startX: number
    startWidth: number
  } | null>(null)

  widthsRef.current = widths

  // A different table (or a new Dev DB query) starts from its own defaults.
  useEffect(() => {
    setWidths({ ...defaultWidths(columns), ...loadWidths(tableId) })
    // Columns are recreated per render; only the table identity should reset widths.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableId])

  useEffect(() => {
    if (drag === null) return
    const move = (event: PointerEvent): void => {
      const next = clampWidth(drag.startWidth + event.clientX - drag.startX)
      setWidths((current) => ({ ...current, [drag.id]: next }))
    }
    const up = (): void => {
      saveWidths(tableId, widthsRef.current)
      setDrag(null)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [drag, tableId])

  const resizeBy = useCallback(
    (column: DataColumn<Row>, delta: number) => {
      const current = widthsRef.current[column.id] ?? column.width ?? MIN_WIDTH
      const next = {
        ...widthsRef.current,
        [column.id]: clampWidth(current + delta),
      }
      setWidths(next)
      saveWidths(tableId, next)
    },
    [tableId],
  )

  const reset = useCallback(() => {
    clearWidths(tableId)
    setWidths(defaultWidths(columns))
  }, [columns, tableId])

  const customised = columns.some(
    (column) =>
      widths[column.id] !== undefined &&
      widths[column.id] !== defaults[column.id],
  )
  const hasFilters = columns.some((column) => column.filter !== undefined)

  return (
    <StackLayout gap={1}>
      {customised ? (
        <FlexLayout justify="end">
          <Button appearance="transparent" onClick={reset}>
            Reset columns
          </Button>
        </FlexLayout>
      ) : null}

      <TableContainer className="data-table-scroll">
        <Table
          zebra={zebra}
          style={{ tableLayout: 'fixed' }}
          className="data-table"
        >
          <colgroup>
            {columns.map((column) => (
              <col
                key={column.id}
                style={
                  widths[column.id] === undefined
                    ? undefined
                    : { width: `${widths[column.id]}px` }
                }
              />
            ))}
          </colgroup>
          <THead>
            <TR>
              {columns.map((column) => (
                <TH
                  key={column.id}
                  className={`data-table-th ${column.className ?? ''}`.trim()}
                  textAlign={column.align}
                  aria-sort={column.ariaSort}
                >
                  {column.header}
                  <span
                    role="separator"
                    aria-orientation="vertical"
                    aria-label={`Resize ${column.label ?? column.id}`}
                    tabIndex={0}
                    className="data-table-resize"
                    onPointerDown={(event) => {
                      event.preventDefault()
                      const current =
                        widthsRef.current[column.id] ?? column.width ?? MIN_WIDTH
                      setDrag({
                        id: column.id,
                        startX: event.clientX,
                        startWidth: current,
                      })
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'ArrowLeft') {
                        event.preventDefault()
                        resizeBy(column, -KEYBOARD_STEP)
                      } else if (event.key === 'ArrowRight') {
                        event.preventDefault()
                        resizeBy(column, KEYBOARD_STEP)
                      }
                    }}
                  />
                </TH>
              ))}
            </TR>
            {hasFilters ? (
              <TR className="job-filter-row">
                {columns.map((column) => (
                  <TH
                    key={`filter-${column.id}`}
                    className={`data-table-th ${column.className ?? ''}`.trim()}
                  >
                    {column.filter}
                  </TH>
                ))}
              </TR>
            ) : null}
          </THead>
          <TBody>
            {rows.map((row, index) => {
              const key = rowKey(row, index)
              return (
                <TR
                  key={key}
                  className={onRowClick ? 'data-table-row-clickable' : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  aria-selected={selectedKey === key ? true : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            onRowClick(row)
                          }
                        }
                      : undefined
                  }
                >
                  {columns.map((column) => (
                    <TD
                      key={column.id}
                      className={column.className}
                      textAlign={column.align}
                    >
                      {column.cell(row)}
                    </TD>
                  ))}
                </TR>
              )
            })}
          </TBody>
        </Table>
      </TableContainer>

      {loading ? (
        <FlexLayout justify="center" gap={1} align="center">
          <Spinner size="small" />
          <Text color="secondary">loading…</Text>
        </FlexLayout>
      ) : null}
      {rows.length === 0 && !loading && empty !== undefined ? empty : null}

      <Pagination
        page={pagination.page}
        size={pagination.size}
        total={pagination.total}
        onPage={pagination.onPage}
        onSize={pagination.onSize}
      />
    </StackLayout>
  )
}
