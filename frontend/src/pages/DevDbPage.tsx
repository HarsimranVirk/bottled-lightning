/**
 * Dev-only database explorer: table list, read-only SQL preview and CSV/Excel exports.
 *
 * The backend hides this surface unless `SF_DEV_TOOLS=1` and, by default, only accepts
 * localhost requests. It never exposes the `sessions` token table.
 */

import type { JSX } from 'react'
import { useMemo, useState } from 'react'
import {
  Banner,
  BannerContent,
  Button,
  Checkbox,
  Dialog,
  DialogCloseButton,
  DialogContent,
  DialogHeader,
  FlexLayout,
  H1,
  MultilineInput,
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
import { Link } from 'react-router-dom'

import type { DevCell, PurgeResult, PurgeScope } from '../api'
import { Pagination } from '../components/Pagination'
import { TableFilter } from '../components/TableFilter'
import { formatDateTime } from '../format'
import { useDevExport, useDevPurge, useDevQuery, useDevTables } from '../queries'

const DEFAULT_SQL = 'SELECT * FROM work_items LIMIT 100;'

interface ColumnFilter {
  text: string
  values: string[]
}

function cellText(cell: DevCell): string {
  return cell === null ? '—' : String(cell)
}

function download(blob: Blob, format: 'csv' | 'xlsx'): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `bottled-lightning-export.${format}`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function DevDbPage(): JSX.Element {
  const [sql, setSql] = useState(DEFAULT_SQL)
  const [filters, setFilters] = useState<Record<string, ColumnFilter>>({})
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(25)
  const [confirmScope, setConfirmScope] = useState<PurgeScope | null>(null)
  const [preview, setPreview] = useState<PurgeResult | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const [purgeResult, setPurgeResult] = useState<PurgeResult | null>(null)
  const [purgeError, setPurgeError] = useState<string | null>(null)
  const tables = useDevTables()
  const query = useDevQuery()
  const exporter = useDevExport()
  const purge = useDevPurge()

  const error = query.error ?? exporter.error ?? tables.error

  function runQuery(): void {
    setFilters({})
    setPage(1)
    query.mutate({ sql, limit: 500 })
  }

  const columnOptions = useMemo(() => {
    const rows = query.data?.rows ?? []
    return (query.data?.columns ?? []).map((_column, index) => {
      const values = new Set<string>()
      for (const row of rows) {
        const cell = row[index] ?? null
        if (cell === null) continue
        const value = cellText(cell)
        if (value.trim() !== '') values.add(value)
      }
      return [...values]
        .sort((left, right) => left.localeCompare(right))
        .slice(0, 100)
        .map((value) => ({ value, label: value }))
    })
  }, [query.data])

  const filteredRows = useMemo(() => {
    const rows = query.data?.rows ?? []
    const active = Object.entries(filters).filter(
      ([, filter]) => filter.text.trim() !== '' || filter.values.length > 0,
    )
    if (active.length === 0) return rows
    return rows.filter((row) =>
      active.every(([index, filter]) => {
        const value = cellText(row[Number(index)] ?? null)
        if (
          filter.text.trim() !== '' &&
          !value.toLowerCase().includes(filter.text.trim().toLowerCase())
        ) {
          return false
        }
        return filter.values.length === 0 || filter.values.includes(value)
      }),
    )
  }, [query.data, filters])

  const pageRows = filteredRows.slice((page - 1) * size, page * size)
  const hasFilters = Object.values(filters).some(
    (filter) => filter.text.trim() !== '' || filter.values.length > 0,
  )

  function updateFilter(index: number, patch: Partial<ColumnFilter>): void {
    setFilters((current) => {
      const key = String(index)
      const existing = current[key] ?? { text: '', values: [] }
      return { ...current, [key]: { ...existing, ...patch } }
    })
    setPage(1)
  }

  function changeSize(next: number): void {
    setSize(next)
    setPage(1)
  }

  async function exportQuery(format: 'csv' | 'xlsx'): Promise<void> {
    const blob = await exporter.mutateAsync({ sql, format })
    download(blob, format)
  }

  function scopeLabel(scope: PurgeScope): string {
    return scope === 'current' ? 'current data' : 'historical data'
  }

  function scopeDescription(scope: PurgeScope): string {
    return scope === 'current'
      ? 'Deletes work items last active more than 24 hours ago, plus their fields, attributes, refs, decisions, edits and events. Items with an active job are skipped. Approved history is untouched.'
      : 'Deletes approved-deviation snapshots accepted more than 90 days ago, plus their fields, attributes, refs and edits. Current work items are untouched.'
  }

  async function openPurge(scope: PurgeScope): Promise<void> {
    setConfirmScope(scope)
    setPreview(null)
    setAcknowledged(false)
    setPurgeResult(null)
    setPurgeError(null)
    try {
      const result = await purge.mutateAsync({ scope, dryRun: true })
      setPreview(result)
    } catch (caught) {
      setPurgeError(caught instanceof Error ? caught.message : 'purge preview failed')
    }
  }

  function closePurge(): void {
    if (purge.isPending) return
    setConfirmScope(null)
    setPreview(null)
    setAcknowledged(false)
  }

  async function runPurge(): Promise<void> {
    if (confirmScope === null || !acknowledged) return
    setPurgeError(null)
    try {
      const result = await purge.mutateAsync({
        scope: confirmScope,
        dryRun: false,
      })
      setPurgeResult(result)
      setConfirmScope(null)
      setPreview(null)
      setAcknowledged(false)
    } catch (caught) {
      setPurgeError(caught instanceof Error ? caught.message : 'purge failed')
    }
  }

  return (
    <StackLayout gap={2}>
      <FlexLayout justify="space-between" align="center" gap={2} wrap>
        <H1>DB explorer</H1>
        <Link to="/dev/states">Back to state harness</Link>
      </FlexLayout>
      <Text color="secondary">
        Read-only queries. The <code>sessions</code> table is hidden and blocked; exports
        use the same query and limits. Maintenance purges are explicit and confirmed
        below.
      </Text>

      {tables.isError ? (
        <Banner status="warning">
          <BannerContent>
            Dev tools are disabled on this server, or this request is not from
            localhost. Remove <code>SF_DEV_TOOLS=0</code> or use a local connection, then
            reload.
          </BannerContent>
        </Banner>
      ) : null}

      <div className="dev-db-grid">
        <StackLayout gap={1}>
          <Text styleAs="h3">Tables</Text>
          {tables.isPending ? <Spinner /> : null}
          <StackLayout gap={0.5}>
            {tables.data?.tables.map((table) => (
              <Button
                key={table.name}
                appearance="transparent"
                onClick={() => setSql(`SELECT * FROM "${table.name}" LIMIT 100;`)}
              >
                {table.name} · {table.rows} rows
              </Button>
            ))}
          </StackLayout>
        </StackLayout>

        <StackLayout gap={1}>
          <Text styleAs="h3">Query</Text>
          <MultilineInput
            value={sql}
            rows={10}
            bordered
            textAreaProps={{
              'aria-label': 'SQL query',
              onChange: (event) => setSql(event.target.value),
            }}
          />
          <FlexLayout gap={1} wrap>
            <Button
              appearance="solid"
              onClick={runQuery}
              disabled={!sql.trim() || query.isPending}
            >
              {query.isPending ? 'Running…' : 'Run query'}
            </Button>
            <Button
              appearance="bordered"
              onClick={() => void exportQuery('csv')}
              disabled={!sql.trim() || exporter.isPending}
            >
              Export CSV
            </Button>
            <Button
              appearance="bordered"
              onClick={() => void exportQuery('xlsx')}
              disabled={!sql.trim() || exporter.isPending}
            >
              Export Excel
            </Button>
          </FlexLayout>
          <Text color="secondary" styleAs="label">
            Exports run the full query, not the filtered table view.
          </Text>
        </StackLayout>
      </div>

      {error ? (
        <Banner status="error">
          <BannerContent>{error.message}</BannerContent>
        </Banner>
      ) : null}

      {query.data ? (
        <StackLayout gap={1}>
          <FlexLayout justify="space-between" align="center" gap={2} wrap>
            <Text color="secondary">
              {filteredRows.length === query.data.rowCount
                ? `${query.data.rowCount} rows`
                : `${filteredRows.length} of ${query.data.rowCount} rows`}
              {' · '}
              {query.data.durationMs} ms
              {query.data.truncated ? ' · truncated to the preview limit' : ''}
            </Text>
            {hasFilters ? (
              <Button
                appearance="transparent"
                onClick={() => {
                  setFilters({})
                  setPage(1)
                }}
              >
                Clear filters
              </Button>
            ) : null}
          </FlexLayout>

          <TableContainer>
            <Table zebra>
              <THead>
                <TR>
                  {query.data.columns.map((column, index) => (
                    <TH key={`${column}-${index}`}>{column}</TH>
                  ))}
                </TR>
                <TR className="job-filter-row">
                  {query.data.columns.map((column, index) => {
                    const filter = filters[String(index)]
                    return (
                      <TH key={`filter-${column}-${index}`}>
                        <TableFilter
                          label={`Filter by ${column}`}
                          text={filter?.text ?? ''}
                          onText={(text) => updateFilter(index, { text })}
                          selected={filter?.values ?? []}
                          onSelected={(values) => updateFilter(index, { values })}
                          options={columnOptions[index] ?? []}
                          placeholder="Filter"
                        />
                      </TH>
                    )
                  })}
                </TR>
              </THead>
              <TBody>
                {pageRows.map((row, rowIndex) => (
                  <TR key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <TD key={cellIndex}>{cellText(cell)}</TD>
                    ))}
                  </TR>
                ))}
              </TBody>
            </Table>
          </TableContainer>

          {pageRows.length === 0 ? (
            <Text color="secondary">No rows match the filters.</Text>
          ) : null}

          <Pagination
            page={page}
            size={size}
            total={filteredRows.length}
            onPage={setPage}
            onSize={changeSize}
          />
        </StackLayout>
      ) : null}

      <StackLayout gap={1}>
        <Text styleAs="h3">Maintenance</Text>
        <Text color="secondary">
          Manual retention only. Current work items are kept for 24 hours; approved
          history is kept for 3 months.
        </Text>
        <FlexLayout gap={1} wrap>
          <Button
            appearance="bordered"
            sentiment="negative"
            onClick={() => void openPurge('current')}
            disabled={confirmScope !== null || purge.isPending}
          >
            Purge current data
          </Button>
          <Button
            appearance="bordered"
            sentiment="negative"
            onClick={() => void openPurge('history')}
            disabled={confirmScope !== null || purge.isPending}
          >
            Purge historical data
          </Button>
        </FlexLayout>
        {purgeError && confirmScope === null ? (
          <Banner status="error">
            <BannerContent>{purgeError}</BannerContent>
          </Banner>
        ) : null}
        {purgeResult ? (
          <Banner status="success">
            <BannerContent>
              Purged {purgeResult.total} rows from {scopeLabel(purgeResult.scope)}. Cutoff{' '}
              {formatDateTime(purgeResult.cutoff)}.
            </BannerContent>
          </Banner>
        ) : null}
      </StackLayout>

      <Dialog
        open={confirmScope !== null}
        onOpenChange={(open) => {
          if (!open) closePurge()
        }}
        size="medium"
      >
        <DialogHeader
          header={
            confirmScope === null
              ? 'Purge data'
              : `Purge ${scopeLabel(confirmScope)}?`
          }
          actions={<DialogCloseButton onClick={closePurge} />}
        />
        <DialogContent>
          <StackLayout gap={1}>
            <Text>{confirmScope === null ? '' : scopeDescription(confirmScope)}</Text>
            {preview === null && purge.isPending ? (
              <FlexLayout gap={1} align="center">
                <Spinner size="small" />
                <Text color="secondary">Calculating the cutoff and counts…</Text>
              </FlexLayout>
            ) : null}
            {preview ? (
              <>
                <Text color="secondary">
                  Cutoff {formatDateTime(preview.cutoff)} · {preview.total} rows
                </Text>
                <TableContainer>
                  <Table>
                    <THead>
                      <TR>
                        <TH>Table</TH>
                        <TH textAlign="right">Rows</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {Object.entries(preview.deleted).map(([table, count]) => (
                        <TR key={table}>
                          <TD>{table}</TD>
                          <TD textAlign="right">{count}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </TableContainer>
                <Checkbox
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                  label="I understand this cannot be undone."
                />
              </>
            ) : null}
            {purgeError ? (
              <Banner status="error">
                <BannerContent>{purgeError}</BannerContent>
              </Banner>
            ) : null}
            <FlexLayout gap={1} justify="end">
              <Button appearance="bordered" onClick={closePurge} disabled={purge.isPending}>
                Cancel
              </Button>
              <Button
                appearance="solid"
                sentiment="negative"
                onClick={() => void runPurge()}
                disabled={!acknowledged || preview === null || purge.isPending}
              >
                {purge.isPending && preview !== null ? 'Purging…' : 'Purge'}
              </Button>
            </FlexLayout>
          </StackLayout>
        </DialogContent>
      </Dialog>
    </StackLayout>
  )
}
