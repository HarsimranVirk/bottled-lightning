/**
 * Accepted-deviations history snapshot: every deviation the deck approved, newest
 * accept first. Salt DS table; pagination is server-side.
 */

import type { JSX } from 'react'
import {
  Button,
  FlexLayout,
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
import type { HistoryFilters } from '../queries'
import { EMPTY_HISTORY_FILTERS } from '../queries'
import { DecisionChip, StatusChip } from './StatusChip'
import { Pagination } from './Pagination'
import { TableFilter } from './TableFilter'
import type { TableFilterOption } from './TableFilter'
import { TableRangeFilter } from './TableRangeFilter'

const STATUSES = [
  'present',
  'extracting',
  'ready',
  'editing',
  'submitting',
  'applying',
  'validating',
  'executing',
  'absent_pending',
  'needs_review',
  'completed',
  'closed',
  'skipped',
]

function uniqueOptions(
  values: string[],
  label: (value: string) => string = (value) => value,
): TableFilterOption[] {
  return [...new Set(values.filter((value) => value.trim() !== ''))]
    .sort((left, right) => left.localeCompare(right))
    .slice(0, 100)
    .map((value) => ({ value, label: label(value) }))
}

function hasFilters(filters: HistoryFilters): boolean {
  return (
    filters.key.trim() !== '' ||
    filters.keys.length > 0 ||
    filters.statusText.trim() !== '' ||
    filters.statuses.length > 0 ||
    filters.approved.trim() !== '' ||
    filters.approvedValues.length > 0 ||
    filters.decidedAfter !== '' ||
    filters.decidedBefore !== '' ||
    Object.values(filters.fieldText).some((text) => text.trim() !== '') ||
    Object.values(filters.fieldValues).some((values) => values.length > 0)
  )
}

interface Props {
  rows: ItemRow[]
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  listUrl: string
  filters: HistoryFilters
  onFilters: (filters: HistoryFilters) => void
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
  filters,
  onFilters,
  page,
  size,
  total,
  onPage,
  onSize,
  loading,
  onOpen,
}: Props): JSX.Element {
  const ordered = orderedFields(fields)
  const keyOptions = uniqueOptions(rows.map((row) => row.key))
  const approvedOptions = uniqueOptions(
    rows.map((row) => row.approvedAt ?? ''),
  )
  const fieldOptions = new Map(
    ordered.map((field) => [
      field.key,
      uniqueOptions(
        rows.map((row) => fieldValue(row.fields, field.key)),
        (value) => displayValue(field, value),
      ),
    ]),
  )
  const filtered = hasFilters(filters)

  function update(patch: Partial<HistoryFilters>): void {
    onFilters({ ...filters, ...patch })
  }

  function updateFieldText(key: string, text: string): void {
    onFilters({
      ...filters,
      fieldText: { ...filters.fieldText, [key]: text },
    })
  }

  function updateFieldValues(key: string, values: string[]): void {
    onFilters({
      ...filters,
      fieldValues: { ...filters.fieldValues, [key]: values },
    })
  }

  return (
    <StackLayout gap={1}>
      <FlexLayout justify="space-between" align="end" gap={2} wrap>
        <Text color="secondary">{total} approved</Text>
        {filtered ? (
          <Button
            appearance="transparent"
            onClick={() => onFilters(EMPTY_HISTORY_FILTERS)}
          >
            Clear filters
          </Button>
        ) : null}
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
            <TR className="job-filter-row">
              <TH>
                <TableFilter
                  label="Filter by deviation"
                  text={filters.key}
                  onText={(text) => update({ key: text })}
                  selected={filters.keys}
                  onSelected={(values) => update({ keys: values })}
                  options={keyOptions}
                  placeholder="Deviation"
                />
              </TH>
              <TH>
                <TableRangeFilter
                  fromLabel="Decided from"
                  toLabel="Decided to"
                  from={filters.decidedAfter}
                  to={filters.decidedBefore}
                  onFrom={(value) => update({ decidedAfter: value })}
                  onTo={(value) => update({ decidedBefore: value })}
                  type="date"
                />
              </TH>
              <TH>
                <TableFilter
                  label="Filter by status"
                  text={filters.statusText}
                  onText={(text) => update({ statusText: text })}
                  selected={filters.statuses}
                  onSelected={(values) => update({ statuses: values })}
                  options={STATUSES.map((value) => ({
                    value,
                    label: value.replace(/_/g, ' '),
                  }))}
                />
              </TH>
              <TH className="history-approval">
                <TableFilter
                  label="Filter by SF approval"
                  text={filters.approved}
                  onText={(text) => update({ approved: text })}
                  selected={filters.approvedValues}
                  onSelected={(values) => update({ approvedValues: values })}
                  options={approvedOptions}
                  placeholder="Approval"
                />
              </TH>
              {ordered.map((field) => (
                <TH key={`filter-${field.key}`} className="history-values">
                  <TableFilter
                    label={`Filter by ${field.label}`}
                    text={filters.fieldText[field.key] ?? ''}
                    onText={(text) => updateFieldText(field.key, text)}
                    selected={filters.fieldValues[field.key] ?? []}
                    onSelected={(values) => updateFieldValues(field.key, values)}
                    options={fieldOptions.get(field.key) ?? []}
                  />
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
          {filtered
            ? 'No approved deviations match these filters.'
            : 'No deviations have been accepted yet.'}
        </Text>
      ) : null}

      <Pagination page={page} size={size} total={total} onPage={onPage} onSize={onSize} />
    </StackLayout>
  )
}
