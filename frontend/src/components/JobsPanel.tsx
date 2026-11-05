/**
 * Jobs table: per-column filters, sortable headers, server-side pagination and the log
 * panel for the selected job. Pure presentation — the page owns filter/page state.
 */

import type { JSX } from 'react'
import {
  Banner,
  BannerContent,
  Button,
  Dropdown,
  FlexLayout,
  H3,
  Input,
  Option,
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
import { formatDateTime, formatDuration } from '../format'
import { Pagination } from './Pagination'
import { StatusChip } from './StatusChip'

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
  return Object.values(filters).some((value) => value.trim() !== '')
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

function SelectFilter({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}): JSX.Element {
  const display = options.find((option) => option.value === value)?.label ?? 'Any'
  return (
    <Dropdown
      aria-label={label}
      value={value ? display : 'Any'}
      selected={[value]}
      onSelectionChange={(_event, selected) => onChange(String(selected[0] ?? ''))}
      style={{ width: '100%', minWidth: 80 }}
    >
      <Option value="">Any</Option>
      {options.map((option) => (
        <Option key={option.value} value={option.value}>
          {option.label}
        </Option>
      ))}
    </Dropdown>
  )
}

function TextFilter({
  label,
  value,
  onChange,
  type,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'date' | 'number'
  placeholder?: string
}): JSX.Element {
  return (
    <Input
      value={value}
      inputProps={{
        'aria-label': label,
        type: type ?? 'text',
        placeholder,
        onChange: (event) => onChange(event.target.value),
      }}
    />
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

  function update<K extends keyof JobFilters>(key: K, value: JobFilters[K]): void {
    onFilters({ ...filters, [key]: value })
  }

  return (
    <div className="jobs">
      {filtered ? (
        <FlexLayout justify="end">
          <Button
            appearance="bordered"
            onClick={() =>
              onFilters({
                id: '',
                status: '',
                kind: '',
                phase: '',
                item: '',
                error: '',
                startedAfter: '',
                startedBefore: '',
                durationMinS: '',
                durationMaxS: '',
              })
            }
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
                  <TextFilter
                    label="Filter by job id"
                    value={filters.id}
                    placeholder="ID"
                    onChange={(value) => update('id', value)}
                  />
                </TH>
                <TH>
                  <SelectFilter
                    label="Filter by status"
                    value={filters.status}
                    options={STATUSES.map((value) => ({
                      value,
                      label: value.replace(/_/g, ' '),
                    }))}
                    onChange={(value) => update('status', value)}
                  />
                </TH>
                <TH>
                  <SelectFilter
                    label="Filter by kind"
                    value={filters.kind}
                    options={KINDS.map((value) => ({ value, label: value }))}
                    onChange={(value) => update('kind', value)}
                  />
                </TH>
                <TH className="job-col-phase">
                  <SelectFilter
                    label="Filter by phase"
                    value={filters.phase}
                    options={PHASES.map((value) => ({ value, label: value }))}
                    onChange={(value) => update('phase', value)}
                  />
                </TH>
                <TH className="job-col-item">
                  <TextFilter
                    label="Filter by item"
                    value={filters.item}
                    placeholder="Item"
                    onChange={(value) => update('item', value)}
                  />
                </TH>
                <TH className="job-col-started">
                  <StackLayout gap={0.5}>
                    <TextFilter
                      label="Started from"
                      type="date"
                      value={filters.startedAfter}
                      onChange={(value) => update('startedAfter', value)}
                    />
                    <TextFilter
                      label="Started to"
                      type="date"
                      value={filters.startedBefore}
                      onChange={(value) => update('startedBefore', value)}
                    />
                  </StackLayout>
                </TH>
                <TH>
                  <StackLayout gap={0.5}>
                    <TextFilter
                      label="Minimum duration in seconds"
                      type="number"
                      placeholder="min"
                      value={filters.durationMinS}
                      onChange={(value) => update('durationMinS', value)}
                    />
                    <TextFilter
                      label="Maximum duration in seconds"
                      type="number"
                      placeholder="max"
                      value={filters.durationMaxS}
                      onChange={(value) => update('durationMaxS', value)}
                    />
                  </StackLayout>
                </TH>
                <TH className="job-col-error">
                  <TextFilter
                    label="Filter by error"
                    value={filters.error}
                    placeholder="Error"
                    onChange={(value) => update('error', value)}
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
