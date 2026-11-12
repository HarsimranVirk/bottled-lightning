/**
 * Jobs table: per-column filters, sortable headers, server-side pagination and the log
 * panel for the selected job. Pure presentation — the page owns filter/page state.
 */

import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import {
  Banner,
  BannerContent,
  Button,
  H3,
  Panel,
  Spinner,
  StackLayout,
  Text,
} from '@salt-ds/core'
import { CheckmarkIcon, CopyIcon } from '@salt-ds/icons'

import type { JobLogs, JobView } from '../api'
import type { JobFilters } from '../queries'
import { EMPTY_JOB_FILTERS } from '../queries'
import { formatDateTime, formatDuration } from '../format'
import type { DataColumn } from './DataTable'
import { DataTable } from './DataTable'
import { StatusChip } from './StatusChip'
import { TableFilter } from './TableFilter'
import type { TableFilterOption } from './TableFilter'
import { TableRangeFilter } from './TableRangeFilter'

const STATUSES = ['queued', 'running', 'blocked_auth', 'succeeded', 'failed', 'cancelled']
const KINDS = ['extract', 'submit']
const PHASES = ['extract', 'apply', 'validate', 'execute']

interface Props {
  jobs: JobView[]
  total: number
  filters: JobFilters
  onFilters: (filters: JobFilters) => void
  sort: string
  order: 'asc' | 'desc'
  onSort: (column: string) => void
  page: number
  size: number
  onPage: (page: number) => void
  onSize: (size: number) => void
  selected: number | null
  logs: JobLogs | undefined
  loadingLogs: boolean
  onSelect: (id: number) => void
  loading: boolean
}

function hasFilters(filters: JobFilters): boolean {
  return Object.values(filters).some((value) =>
    Array.isArray(value) ? value.length > 0 : value.trim() !== '',
  )
}

function uniqueOptions(values: string[], prefix = ''): TableFilterOption[] {
  return [...new Set(values.filter((value) => value.trim() !== ''))]
    .sort((left, right) => left.localeCompare(right))
    .slice(0, 100)
    .map((value) => ({ value, label: `${prefix}${value}` }))
}

function SortHeader({
  label,
  sort,
  order,
  column,
  onSort,
}: {
  label: string
  sort: string
  order: 'asc' | 'desc'
  column: string
  onSort: (column: string) => void
}): JSX.Element {
  const active = sort === column
  return (
    <Button appearance="transparent" onClick={() => onSort(column)}>
      {label}
      {active ? (order === 'asc' ? ' ▲' : ' ▼') : ''}
    </Button>
  )
}

function sortState(
  column: string,
  sort: string,
  order: 'asc' | 'desc',
): 'ascending' | 'descending' | 'none' {
  if (sort !== column) return 'none'
  return order === 'asc' ? 'ascending' : 'descending'
}

export function JobsPanel({
  jobs,
  total,
  filters,
  onFilters,
  sort,
  order,
  onSort,
  page,
  size,
  onPage,
  onSize,
  selected,
  logs,
  loadingLogs,
  onSelect,
  loading,
}: Props): JSX.Element {
  const [copiedId, setCopiedId] = useState<number | null>(null)

  // Revert the tick back to the copy icon a couple of seconds after a copy.
  useEffect(() => {
    if (copiedId === null) return
    const timer = setTimeout(() => setCopiedId(null), 2000)
    return () => clearTimeout(timer)
  }, [copiedId])

  const filtered = hasFilters(filters)
  const idOptions = uniqueOptions(jobs.map((job) => String(job.id)), '#')
  const itemOptions = uniqueOptions(jobs.map((job) => job.item))
  const errorOptions = uniqueOptions(
    jobs.flatMap((job) => (job.error ? [job.error] : [])),
  )

  function update<K extends keyof JobFilters>(key: K, value: JobFilters[K]): void {
    onFilters({ ...filters, [key]: value })
  }

  /**
   * Copies the selected job's log lines to the clipboard. Runs from the log panel's
   * "Copy logs" button; failures (e.g. a non-secure LAN origin without clipboard
   * access) are swallowed so the label simply stays "Copy logs".
   */
  async function copyLogs(): Promise<void> {
    if (selected === null) return
    try {
      await navigator.clipboard.writeText(logs?.logs.join('\n') ?? '')
      setCopiedId(selected)
    } catch {
      setCopiedId(null)
    }
  }

  const columns: DataColumn<JobView>[] = [
    {
      id: 'id',
      label: 'ID',
      width: 80,
      ariaSort: sortState('id', sort, order),
      header: (
        <SortHeader column="id" label="ID" sort={sort} order={order} onSort={onSort} />
      ),
      filter: (
        <TableFilter
          label="Filter by job id"
          text={filters.id}
          onText={(value) => update('id', value)}
          selected={filters.ids}
          onSelected={(value) => update('ids', value)}
          options={idOptions}
          placeholder="ID"
        />
      ),
      cell: (job) => <span className="mono">#{job.id}</span>,
    },
    {
      id: 'status',
      label: 'Status',
      width: 130,
      ariaSort: sortState('status', sort, order),
      header: (
        <SortHeader
          column="status"
          label="Status"
          sort={sort}
          order={order}
          onSort={onSort}
        />
      ),
      filter: (
        <TableFilter
          label="Filter by status"
          text={filters.statusText}
          onText={(value) => update('statusText', value)}
          selected={filters.statuses}
          onSelected={(value) => update('statuses', value)}
          options={STATUSES.map((value) => ({
            value,
            label: value.replace(/_/g, ' '),
          }))}
          textMode="search"
        />
      ),
      cell: (job) => <StatusChip status={job.status} />,
    },
    {
      id: 'kind',
      label: 'Kind',
      width: 100,
      ariaSort: sortState('kind', sort, order),
      header: (
        <SortHeader column="kind" label="Kind" sort={sort} order={order} onSort={onSort} />
      ),
      filter: (
        <TableFilter
          label="Filter by kind"
          text={filters.kindText}
          onText={(value) => update('kindText', value)}
          selected={filters.kinds}
          onSelected={(value) => update('kinds', value)}
          options={KINDS.map((value) => ({ value, label: value }))}
        />
      ),
      cell: (job) => job.kind,
    },
    {
      id: 'phase',
      label: 'Phase',
      width: 120,
      className: 'job-col-phase',
      ariaSort: sortState('phase', sort, order),
      header: (
        <SortHeader
          column="phase"
          label="Phase"
          sort={sort}
          order={order}
          onSort={onSort}
        />
      ),
      filter: (
        <TableFilter
          label="Filter by phase"
          text={filters.phaseText}
          onText={(value) => update('phaseText', value)}
          selected={filters.phases}
          onSelected={(value) => update('phases', value)}
          options={PHASES.map((value) => ({ value, label: value }))}
        />
      ),
      cell: (job) => job.phase ?? '—',
    },
    {
      id: 'item',
      label: 'Item',
      width: 230,
      className: 'job-col-item',
      ariaSort: sortState('item', sort, order),
      header: (
        <SortHeader column="item" label="Item" sort={sort} order={order} onSort={onSort} />
      ),
      filter: (
        <TableFilter
          label="Filter by item"
          text={filters.item}
          onText={(value) => update('item', value)}
          selected={filters.items}
          onSelected={(value) => update('items', value)}
          options={itemOptions}
          placeholder="Item"
        />
      ),
      cell: (job) => <span className="mono">{job.item}</span>,
    },
    {
      id: 'started',
      label: 'Started',
      width: 180,
      className: 'job-col-started',
      ariaSort: sortState('started', sort, order),
      header: (
        <SortHeader
          column="started"
          label="Started"
          sort={sort}
          order={order}
          onSort={onSort}
        />
      ),
      filter: (
        <TableRangeFilter
          fromLabel="Started from"
          toLabel="Started to"
          from={filters.startedAfter}
          to={filters.startedBefore}
          onFrom={(value) => update('startedAfter', value)}
          onTo={(value) => update('startedBefore', value)}
          type="date"
        />
      ),
      cell: (job) => formatDateTime(job.startedAt),
    },
    {
      id: 'duration',
      label: 'Duration',
      width: 110,
      align: 'right',
      ariaSort: sortState('duration', sort, order),
      header: (
        <SortHeader
          column="duration"
          label="Duration"
          sort={sort}
          order={order}
          onSort={onSort}
        />
      ),
      filter: (
        <TableRangeFilter
          fromLabel="Minimum duration in seconds"
          toLabel="Maximum duration in seconds"
          from={filters.durationMinS}
          to={filters.durationMaxS}
          onFrom={(value) => update('durationMinS', value)}
          onTo={(value) => update('durationMaxS', value)}
          type="number"
          fromPlaceholder="min"
          toPlaceholder="max"
        />
      ),
      cell: (job) => (
        <span className="num mono">{formatDuration(job.durationMs)}</span>
      ),
    },
    {
      id: 'error',
      label: 'Error',
      width: 240,
      className: 'job-col-error',
      ariaSort: sortState('error', sort, order),
      header: (
        <SortHeader
          column="error"
          label="Error"
          sort={sort}
          order={order}
          onSort={onSort}
        />
      ),
      filter: (
        <TableFilter
          label="Filter by error"
          text={filters.error}
          onText={(value) => update('error', value)}
          selected={filters.errors}
          onSelected={(value) => update('errors', value)}
          options={errorOptions}
          placeholder="Error"
        />
      ),
      cell: (job) => (
        <span className="job-error" title={job.error ?? undefined}>
          {job.error ?? '—'}
        </span>
      ),
    },
  ]

  return (
    <div className="jobs">
      {filtered ? (
        <StackLayout gap={1} align="end">
          <Button
            appearance="bordered"
            onClick={() => onFilters(EMPTY_JOB_FILTERS)}
          >
            Clear filters
          </Button>
        </StackLayout>
      ) : null}

      <DataTable
        tableId="jobs"
        columns={columns}
        rows={jobs}
        rowKey={(job) => String(job.id)}
        onRowClick={(job) => onSelect(job.id)}
        selectedKey={selected === null ? null : String(selected)}
        loading={loading}
        empty={
          <Text color="secondary">
            {filtered ? 'No jobs match these filters.' : 'Nothing has run yet.'}
          </Text>
        }
        pagination={{ page, size, total, onPage, onSize }}
      />

      {selected !== null ? (
        <StackLayout gap={1} className="job-logs">
          <H3>Job #{selected}</H3>
          {loadingLogs ? <Spinner size="small" /> : null}
          <div className="job-logs-output">
            <Button
              appearance="transparent"
              aria-label={copiedId === selected ? 'Copied' : 'Copy logs'}
              title={copiedId === selected ? 'Copied' : 'Copy logs'}
              className="job-logs-copy"
              onClick={() => void copyLogs()}
            >
              {copiedId === selected ? <CheckmarkIcon /> : <CopyIcon />}
            </Button>
            <Panel>
              <pre className="job-logs-pre">{logs?.logs.join('\n') ?? ''}</pre>
            </Panel>
          </div>
          {logs?.job.error ? (
            <Banner status="error">
              <BannerContent>{logs.job.error}</BannerContent>
            </Banner>
          ) : null}
        </StackLayout>
      ) : null}
    </div>
  )
}
