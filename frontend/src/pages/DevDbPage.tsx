/**
 * Dev-only database explorer: table list, read-only SQL preview and CSV/Excel exports.
 *
 * The backend hides this surface unless `SF_DEV_TOOLS=1` and, by default, only accepts
 * localhost requests. It never exposes the `sessions` token table.
 */

import type { JSX } from 'react'
import { useState } from 'react'
import {
  Banner,
  BannerContent,
  Button,
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

import type { DevCell } from '../api'
import { useDevExport, useDevQuery, useDevTables } from '../queries'

const DEFAULT_SQL = 'SELECT * FROM work_items LIMIT 100;'

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
  const tables = useDevTables()
  const query = useDevQuery()
  const exporter = useDevExport()

  const error = query.error ?? exporter.error ?? tables.error

  async function exportQuery(format: 'csv' | 'xlsx'): Promise<void> {
    const blob = await exporter.mutateAsync({ sql, format })
    download(blob, format)
  }

  return (
    <StackLayout gap={2}>
      <FlexLayout justify="space-between" align="center" gap={2} wrap>
        <H1>DB explorer</H1>
        <Link to="/dev/states">Back to state harness</Link>
      </FlexLayout>
      <Text color="secondary">
        Read-only. The <code>sessions</code> table is hidden and blocked; exports use the
        same query and limits.
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
              onClick={() => query.mutate({ sql, limit: 500 })}
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
        </StackLayout>
      </div>

      {error ? (
        <Banner status="error">
          <BannerContent>{error.message}</BannerContent>
        </Banner>
      ) : null}

      {query.data ? (
        <StackLayout gap={1}>
          <Text color="secondary">
            {query.data.rowCount} rows · {query.data.durationMs} ms
            {query.data.truncated ? ' · truncated to the preview limit' : ''}
          </Text>
          <TableContainer>
            <Table>
              <THead>
                <TR>
                  {query.data.columns.map((column, index) => (
                    <TH key={`${column}-${index}`}>{column}</TH>
                  ))}
                </TR>
              </THead>
              <TBody>
                {query.data.rows.map((row, rowIndex) => (
                  <TR key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <TD key={cellIndex}>{cellText(cell)}</TD>
                    ))}
                  </TR>
                ))}
              </TBody>
            </Table>
          </TableContainer>
        </StackLayout>
      ) : null}
    </StackLayout>
  )
}
