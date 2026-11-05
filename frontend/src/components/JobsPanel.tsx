/**
 * Jobs table: per-column filters, sortable headers, server-side pagination and the log
 * panel for the selected job. Pure presentation — the page owns filter/page state.
 */

import type { JSX } from 'react'
import {
  Banner,
  BannerContent,
  Button,
  FlexLayout,
  H3,
  Panel,
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

import type { JobLogs, JobView } from '../api'
import type { JobFilters } from '../queries'
import { EMPTY_JOB_FILTERS } from '../queries'
import { formatDateTime, formatDuration } from '../format'
import { Pagination } from './Pagination'
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
  column,
  label,
  sort,
  order,
  onSort,
  className,
  textAlign,
}: {
  column: string
  label: string
  sort: string
  order: 'asc' | 'desc'
  onSort: (column: string) => void
  className?: string
  textAlign?: 'left' | 'right'
}): JSX.Element {
  const active = sort === column
  const ariaSort = active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'
  return (
    <TH aria-sort={ariaSort} className={className} textAlign={textAlign}>
      <Button appearance="transparent" onClick={() => onSort(column)}>
        {label}
        {active ? (order === 'asc' ? ' ▲' : ' ▼') : ''}
      </Button>
    </TH>
  )
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
  const filtered = hasFilters(filters)
  const idOptions = uniqueOptions(jobs.map((job) => String(job.id)), '#')
  const itemOptions = uniqueOptions(jobs.map((job) => job.item))
  const errorOptions = uniqueOptions(
    jobs.flatMap((job) => (job.error ? [job.error] : [])),
  )

  function update<K extends keyof JobFilters>(key: K, value: JobFilters[K]): void {
    onFilters({ ...filters, [key]: value })
  }

  return (
    <div className="jobs">
      {filtered ? (
        <FlexLayout justify="end">
          <Button
            appearance="bordered"
            onClick={() => onFilters(EMPTY_JOB_FILTERS)}
          >
            Clear filters
          </Button>
        </FlexLayout>
      ) : null}

      <div className="job-table-wrap">
        <TableContainer>
          <Table>
            <THead>
              <TR>
                <SortHeader column="id" label="ID" sort={sort} order={order} onSort={onSort} />
                <SortHeader column="status" label="Status" sort={sort} order={order} onSort={onSort} />
                <SortHeader column="kind" label="Kind" sort={sort} order={order} onSort={onSort} />
                <SortHeader
                  column="phase"
                  label="Phase"
                  sort={sort}
                  order={order}
                  onSort={onSort}
                  className="job-col-phase"
                />
                <SortHeader
                  column="item"
                  label="Item"
                  sort={sort}
                  order={order}
                  onSort={onSort}
                  className="job-col-item"
                />
                <SortHeader
                  column="started"
                  label="Started"
                  sort={sort}
                  order={order}
                  onSort={onSort}
                  className="job-col-started"
                />
                <SortHeader
                  column="duration"
                  label="Duration"
                  sort={sort}
                  order={order}
                  onSort={onSort}
                  textAlign="right"
                />
                <SortHeader
                  column="error"
                  label="Error"
                  sort={sort}
                  order={order}
                  onSort={onSort}
                  className="job-col-error"
                />
              </TR>
              <TR className="job-filter-row">
                <TH>
                  <TableFilter
                    label="Filter by job id"
                    text={filters.id}
                    onText={(value) => update('id', value)}
                    selected={filters.ids}
                    onSelected={(value) => update('ids', value)}
                    options={idOptions}
                    placeholder="ID"
                  />
                </TH>
                <TH>
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
                  />
                </TH>
                <TH>
                  <TableFilter
                    label="Filter by kind"
                    text={filters.kindText}
                    onText={(value) => update('kindText', value)}
                    selected={filters.kinds}
                    onSelected={(value) => update('kinds', value)}
                    options={KINDS.map((value) => ({ value, label: value }))}
                  />
                </TH>
                <TH className="job-col-phase">
                  <TableFilter
                    label="Filter by phase"
                    text={filters.phaseText}
                    onText={(value) => update('phaseText', value)}
                    selected={filters.phases}
                    onSelected={(value) => update('phases', value)}
                    options={PHASES.map((value) => ({ value, label: value }))}
                  />
                </TH>
                <TH className="job-col-item">
                  <TableFilter
                    label="Filter by item"
                    text={filters.item}
                    onText={(value) => update('item', value)}
                    selected={filters.items}
                    onSelected={(value) => update('items', value)}
                    options={itemOptions}
                    placeholder="Item"
                  />
                </TH>
                <TH className="job-col-started">
                  <TableRangeFilter
                    fromLabel="Started from"
                    toLabel="Started to"
                    from={filters.startedAfter}
                    to={filters.startedBefore}
                    onFrom={(value) => update('startedAfter', value)}
                    onTo={(value) => update('startedBefore', value)}
                    type="date"
                  />
                </TH>
                <TH>
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
                </TH>
                <TH className="job-col-error">
                  <TableFilter
                    label="Filter by error"
                    text={filters.error}
                    onText={(value) => update('error', value)}
                    selected={filters.errors}
                    onSelected={(value) => update('errors', value)}
                    options={errorOptions}
                    placeholder="Error"
                  />
                </TH>
              </TR>
            </THead>
            <TBody>
              {jobs.map((job) => (
                <TR
                  key={job.id}
                  tabIndex={0}
                  className="job-row"
                  aria-selected={job.id === selected}
                  onClick={() => onSelect(job.id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelect(job.id)
                    }
                  }}
                >
                  <TD className="mono">#{job.id}</TD>
                  <TD>
                    <StatusChip status={job.status} />
                  </TD>
                  <TD>{job.kind}</TD>
                  <TD className="job-col-phase">{job.phase ?? '—'}</TD>
                  <TD className="mono job-col-item">{job.item}</TD>
                  <TD className="job-col-started">{formatDateTime(job.startedAt)}</TD>
                  <TD className="num mono" textAlign="right">
                    {formatDuration(job.durationMs)}
                  </TD>
                  <TD className="job-error job-col-error" title={job.error ?? undefined}>
                    {job.error ?? '—'}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </TableContainer>
        {loading ? (
          <div className="job-loading">
            <Spinner size="small" />
          </div>
        ) : null}
        {jobs.length === 0 && !loading ? (
          <Text color="secondary" className="job-empty">
            {filtered ? 'No jobs match these filters.' : 'Nothing has run yet.'}
          </Text>
        ) : null}
      </div>

      <Pagination page={page} size={size} total={total} onPage={onPage} onSize={onSize} />

      {selected !== null ? (
        <StackLayout gap={1} className="job-logs">
          <H3>Job #{selected}</H3>
          {loadingLogs ? <Spinner size="small" /> : null}
          <Panel>
            <pre className="job-logs-pre">{logs?.logs.join('\n') ?? ''}</pre>
          </Panel>
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
