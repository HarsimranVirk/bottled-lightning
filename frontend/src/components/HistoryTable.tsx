/**
 * Accepted-deviations history snapshot: every deviation the deck approved, newest
 * accept first. Rendered by the shared `DataTable`; pagination is server-side.
 */

import type { JSX } from 'react'
import { Button, FlexLayout, Link, StackLayout, Text } from '@salt-ds/core'

import type { HistoryRow, WorkflowFieldView } from '../api'
import {
  absoluteUrl,
  displayValue,
  fieldValue,
  formatDateTime,
  orderedFields,
  statusLabel,
} from '../format'
import type { HistoryFilters } from '../queries'
import { EMPTY_HISTORY_FILTERS } from '../queries'
import type { DataColumn } from './DataTable'
import { DataTable } from './DataTable'
import { DecisionChip, StatusChip } from './StatusChip'
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

/** The five snapshot object links, in display order. */
const REF_COLUMNS = [
  { kind: 'opportunity', label: 'Opportunity' },
  { kind: 'cl_contract', label: 'CL contract' },
  { kind: 'collateral', label: 'Collateral' },
  { kind: 'lms2_cl_contract', label: 'LMS2 CL contract' },
  { kind: 'lms2_collateral', label: 'LMS2 collateral' },
] as const

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
    Object.values(filters.fieldValues).some((values) => values.length > 0) ||
    Object.values(filters.refText).some((text) => text.trim() !== '') ||
    Object.values(filters.refValues).some((values) => values.length > 0)
  )
}

interface Props {
  rows: HistoryRow[]
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
  const approvedOptions = uniqueOptions(rows.map((row) => row.approvedAt ?? ''))
  const fieldOptions = new Map(
    ordered.map((field) => [
      field.key,
      uniqueOptions(
        rows.map((row) => fieldValue(row.fields, field.key)),
        (value) => displayValue(field, value),
      ),
    ]),
  )
  const refOptions = new Map(
    REF_COLUMNS.map((column) => [
      column.kind,
      uniqueOptions(
        rows.flatMap((row) =>
          row.refs.filter((ref) => ref.kind === column.kind).map((ref) => ref.name),
        ),
      ),
    ]),
  )
  const filtered = hasFilters(filters)

  function update(patch: Partial<HistoryFilters>): void {
    onFilters({ ...filters, ...patch })
  }

  function updateFieldText(key: string, text: string): void {
    onFilters({ ...filters, fieldText: { ...filters.fieldText, [key]: text } })
  }

  function updateFieldValues(key: string, values: string[]): void {
    onFilters({ ...filters, fieldValues: { ...filters.fieldValues, [key]: values } })
  }

  function updateRefText(kind: string, text: string): void {
    onFilters({ ...filters, refText: { ...filters.refText, [kind]: text } })
  }

  function updateRefValues(kind: string, values: string[]): void {
    onFilters({ ...filters, refValues: { ...filters.refValues, [kind]: values } })
  }

  const columns: DataColumn<HistoryRow>[] = [
    {
      id: 'key',
      label: 'Deviation',
      header: 'Deviation',
      width: 220,
      filter: (
        <TableFilter
          label="Filter by deviation"
          text={filters.key}
          onText={(text) => update({ key: text })}
          selected={filters.keys}
          onSelected={(values) => update({ keys: values })}
          options={keyOptions}
          placeholder="Deviation"
        />
      ),
      cell: (row) => {
        const href = row.recordUrl ? absoluteUrl(row.recordUrl, listUrl) : null
        return href ? (
          <Link
            href={href}
            target="_blank"
            onClick={(event) => event.stopPropagation()}
          >
            {row.key}
          </Link>
        ) : (
          row.key
        )
      },
    },
    {
      id: 'decided',
      label: 'Decided',
      header: 'Decided',
      width: 190,
      filter: (
        <TableRangeFilter
          fromLabel="Decided from"
          toLabel="Decided to"
          from={filters.decidedAfter}
          to={filters.decidedBefore}
          onFrom={(value) => update({ decidedAfter: value })}
          onTo={(value) => update({ decidedBefore: value })}
          type="date"
        />
      ),
      cell: (row) => (
        <FlexLayout gap={1} align="center">
          {row.decision ? <DecisionChip decision={row.decision.decision} /> : null}
          <span>{formatDateTime(row.decision?.at)}</span>
        </FlexLayout>
      ),
    },
    {
      id: 'status',
      label: 'Status',
      header: 'Status',
      width: 130,
      filter: (
        <TableFilter
          label="Filter by status"
          text={filters.statusText}
          onText={(text) => update({ statusText: text })}
          selected={filters.statuses}
          onSelected={(values) => update({ statuses: values })}
          options={STATUSES.map((value) => ({
            value,
            label: statusLabel(value, terminalLabels),
          }))}
          textMode="search"
        />
      ),
      cell: (row) => <StatusChip status={row.status} labels={terminalLabels} />,
    },
    {
      id: 'approval',
      label: 'SF approval',
      header: 'SF approval',
      width: 120,
      className: 'history-approval',
      filter: (
        <TableFilter
          label="Filter by SF approval"
          text={filters.approved}
          onText={(text) => update({ approved: text })}
          selected={filters.approvedValues}
          onSelected={(values) => update({ approvedValues: values })}
          options={approvedOptions}
          placeholder="Approval"
        />
      ),
      cell: (row) => row.approvedAt ?? '—',
    },
    ...REF_COLUMNS.map(
      (column): DataColumn<HistoryRow> => ({
        id: column.kind,
        label: column.label,
        header: column.label,
        width: 150,
        className: 'history-ref',
        filter: (
          <TableFilter
            label={`Filter by ${column.label}`}
            text={filters.refText[column.kind] ?? ''}
            onText={(text) => updateRefText(column.kind, text)}
            selected={filters.refValues[column.kind] ?? []}
            onSelected={(values) => updateRefValues(column.kind, values)}
            options={refOptions.get(column.kind) ?? []}
            placeholder="Linked object"
          />
        ),
        cell: (row) => {
          const ref = row.refs.find((entry) => entry.kind === column.kind)
          const href = ref ? absoluteUrl(ref.url, listUrl) : null
          return ref && href ? (
            <Link
              href={href}
              target="_blank"
              onClick={(event) => event.stopPropagation()}
            >
              {ref.name}
            </Link>
          ) : (
            '—'
          )
        },
      }),
    ),
    ...ordered.map(
      (field): DataColumn<HistoryRow> => ({
        id: `field-${field.key}`,
        label: field.label,
        header: field.label,
        width: 150,
        align: field.valueType === 'text' ? 'left' : 'right',
        className: 'history-values',
        filter: (
          <TableFilter
            label={`Filter by ${field.label}`}
            text={filters.fieldText[field.key] ?? ''}
            onText={(text) => updateFieldText(field.key, text)}
            selected={filters.fieldValues[field.key] ?? []}
            onSelected={(values) => updateFieldValues(field.key, values)}
            options={fieldOptions.get(field.key) ?? []}
          />
        ),
        cell: (row) => (
          <span className="mono">
            {displayValue(field, fieldValue(row.fields, field.key))}
          </span>
        ),
      }),
    ),
  ]

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

      <DataTable
        tableId="history"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.key}
        onRowClick={(row) => onOpen(row.key)}
        zebra
        loading={loading}
        empty={
          <Text color="secondary">
            {filtered
              ? 'No approved deviations match these filters.'
              : 'No deviations have been accepted yet.'}
          </Text>
        }
        pagination={{ page, size, total, onPage, onSize }}
      />
    </StackLayout>
  )
}
