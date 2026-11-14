/**
 * Durable LMS2 approval audit: one row per contract, updated after each job.
 *
 * The snapshot store survives the 24-hour current-data purge, so this is the single
 * approvals table: it shows queued, in-flight, failed and completed contracts without a
 * separate live queue.
 */

import type { JSX } from 'react'
import { Link, Text } from '@salt-ds/core'

import type { HistoryRow } from '../api'
import type { HistoryFilters } from '../queries'
import { formatDateTime, statusLabel } from '../format'
import type { DataColumn } from './DataTable'
import { DataTable } from './DataTable'
import { StatusChip } from './StatusChip'
import { TableFilter } from './TableFilter'
import type { TableFilterOption } from './TableFilter'
import { TableRangeFilter } from './TableRangeFilter'

const STATUSES = [
  'present',
  'ready',
  'editing',
  'submitting',
  'applying',
  'validating',
  'executing',
  'needs_review',
  'completed',
  'closed',
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

interface Props {
  rows: HistoryRow[]
  total: number
  filters: HistoryFilters
  onFilters: (filters: HistoryFilters) => void
  page: number
  size: number
  onPage: (page: number) => void
  onSize: (size: number) => void
  loading: boolean
  terminalLabels: Record<string, string>
}

/** Contract, request time, current state and the audit reason. */
export function ApprovalHistoryTable({
  rows,
  total,
  filters,
  onFilters,
  page,
  size,
  onPage,
  onSize,
  loading,
  terminalLabels,
}: Props): JSX.Element {
  const keyOptions = uniqueOptions(rows.map((row) => row.key))
  const statusOptions = uniqueOptions(STATUSES, (value) =>
    statusLabel(value, terminalLabels),
  )

  function update(patch: Partial<HistoryFilters>): void {
    onFilters({ ...filters, ...patch })
  }

  const columns: DataColumn<HistoryRow>[] = [
    {
      id: 'contract',
      label: 'Contract',
      header: 'Contract',
      width: 260,
      filter: (
        <TableFilter
          label="Filter by contract"
          text={filters.key}
          onText={(text) => update({ key: text })}
          selected={filters.keys}
          onSelected={(keys) => update({ keys })}
          options={keyOptions}
          placeholder="Contract"
        />
      ),
      cell: (row) => {
        const ref = row.refs.find((entry) => entry.kind === 'lms2_cl_contract')
        const href = row.recordUrl ?? ref?.url ?? ''
        return href ? (
          <Link href={href} target="_blank">
            {row.key}
          </Link>
        ) : (
          row.key
        )
      },
    },
    {
      id: 'requested',
      label: 'Requested',
      header: 'Requested',
      width: 190,
      filter: (
        <TableRangeFilter
          fromLabel="Requested from"
          toLabel="Requested to"
          from={filters.decidedAfter}
          to={filters.decidedBefore}
          onFrom={(value) => update({ decidedAfter: value })}
          onTo={(value) => update({ decidedBefore: value })}
          type="date"
        />
      ),
      cell: (row) => formatDateTime(row.decision?.at),
    },
    {
      id: 'status',
      label: 'Status',
      header: 'Status',
      width: 150,
      filter: (
        <TableFilter
          label="Filter by status"
          text={filters.statusText}
          onText={(text) => update({ statusText: text })}
          selected={filters.statuses}
          onSelected={(statuses) => update({ statuses })}
          options={statusOptions}
          textMode="search"
        />
      ),
      cell: (row) => (
        <StatusChip status={row.status} labels={terminalLabels} />
      ),
    },
    {
      id: 'reason',
      label: 'Reason',
      header: 'Reason',
      width: 300,
      cell: (row) => row.reason ?? '—',
    },
  ]

  const filtered =
    filters.key !== '' ||
    filters.keys.length > 0 ||
    filters.statusText !== '' ||
    filters.statuses.length > 0 ||
    filters.decidedAfter !== '' ||
    filters.decidedBefore !== ''

  return (
    <DataTable
      tableId="lms2-approval-history"
      columns={columns}
      rows={rows}
      rowKey={(row) => row.key}
      zebra
      loading={loading}
      empty={
        <Text color="secondary">
          {filtered
            ? 'No approvals match these filters.'
            : 'No contracts have been queued yet.'}
        </Text>
      }
      pagination={{ page, size, total, onPage, onSize }}
    />
  )
}
