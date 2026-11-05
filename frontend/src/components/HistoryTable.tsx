/**
 * Accepted-deviations history: every deviation the deck approved, newest decision
 * first. Salt DS table; pagination is server-side.
 */

import type { JSX } from 'react'
import {
  FlexLayout,
  FormField,
  FormFieldLabel,
  Input,
  Link,
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

import type { ItemRow, WorkflowFieldView } from '../api'
import { absoluteUrl, displayValue, fieldValue, formatDateTime, orderedFields } from '../format'
import { DecisionChip, StatusChip } from './StatusChip'
import { Pagination } from './Pagination'

interface Props {
  rows: ItemRow[]
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  listUrl: string
  query: string
  onQuery: (query: string) => void
  page: number
  size: number
  total: number
  onPage: (page: number) => void
  onSize: (size: number) => void
  loading: boolean
  onOpen: (key: string) => void
}

export function HistoryTable({
  rows,
  fields,
  terminalLabels,
  listUrl,
  query,
  onQuery,
  page,
  size,
  total,
  onPage,
  onSize,
  loading,
  onOpen,
}: Props): JSX.Element {
  const ordered = orderedFields(fields)

  return (
    <StackLayout gap={1}>
      <FlexLayout justify="space-between" align="end" gap={2} wrap>
        <FormField className="history-search">
          <FormFieldLabel>Search</FormFieldLabel>
          <Input
            value={query}
            inputProps={{
              'aria-label': 'Search approved deviations',
              placeholder: 'Deviation number',
              onChange: (event) => onQuery(event.target.value),
            }}
          />
        </FormField>
        <Text color="secondary">{total} approved</Text>
      </FlexLayout>

      <TableContainer>
        <Table zebra>
          <THead>
            <TR>
              <TH>Deviation</TH>
              <TH>Decided</TH>
              <TH>Status</TH>
              <TH className="history-approval">SF approval</TH>
              {ordered.map((field) => (
                <TH
                  key={field.key}
                  className="history-values"
                  textAlign={field.valueType === 'text' ? 'left' : 'right'}
                >
                  {field.label}
                </TH>
              ))}
            </TR>
          </THead>
          <TBody>
            {rows.map((row) => {
              const recordHref = row.recordUrl ? absoluteUrl(row.recordUrl, listUrl) : null
              return (
                <TR
                  key={row.key}
                  tabIndex={0}
                  className="history-row"
                  onClick={() => onOpen(row.key)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onOpen(row.key)
                    }
                  }}
                >
                  <TD>
                    {recordHref ? (
                      <Link
                        href={recordHref}
                        target="_blank"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {row.key}
                      </Link>
                    ) : (
                      row.key
                    )}
                  </TD>
                  <TD>
                    <FlexLayout gap={1} align="center">
                      {row.decision ? <DecisionChip decision={row.decision.decision} /> : null}
                      <span>{formatDateTime(row.decision?.at)}</span>
                    </FlexLayout>
                  </TD>
                  <TD>
                    <StatusChip status={row.status} labels={terminalLabels} />
                  </TD>
                  <TD className="history-approval">{row.approvedAt ?? '—'}</TD>
                  {ordered.map((field) => (
                    <TD
                      key={field.key}
                      className="history-values mono"
                      textAlign={field.valueType === 'text' ? 'left' : 'right'}
                    >
                      {displayValue(field, fieldValue(row.fields, field.key))}
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
          <Text color="secondary">loading history…</Text>
        </FlexLayout>
      ) : null}
      {rows.length === 0 && !loading ? (
        <Text color="secondary">
          {query.trim() ? 'No approved deviations match this search.' : 'No deviations have been accepted yet.'}
        </Text>
      ) : null}

      <Pagination page={page} size={size} total={total} onPage={onPage} onSize={onSize} />
    </StackLayout>
  )
}
