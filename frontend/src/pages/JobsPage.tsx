/** Jobs screen: paginated, filterable table with per-job logs. */

import type { JSX } from 'react'
import { Banner, BannerContent, FlexLayout, H1, Spinner } from '@salt-ds/core'
import { useState } from 'react'

import { JobsPanel } from '../components/JobsPanel'
import type { JobFilters } from '../queries'
import { EMPTY_JOB_FILTERS, useJobLogs, useJobs } from '../queries'

export function JobsPage(): JSX.Element {
  const [filters, setFilters] = useState<JobFilters>(EMPTY_JOB_FILTERS)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(25)
  const [sort, setSort] = useState('id')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [selected, setSelected] = useState<number | null>(null)

  const jobs = useJobs(filters, page, size, sort, order)
  const logs = useJobLogs(selected)

  function changeFilters(next: JobFilters): void {
    setFilters(next)
    setPage(1)
  }

  function changeSort(column: string): void {
    if (column === sort) {
      setOrder(order === 'asc' ? 'desc' : 'asc')
    } else {
      setSort(column)
      setOrder('asc')
    }
    setPage(1)
  }

  if (jobs.isLoading && !jobs.data) return <Spinner />

  return (
    <FlexLayout direction="column" gap={2}>
      <H1>Jobs</H1>
      {jobs.error ? (
        <Banner status="error">
          <BannerContent>{jobs.error.message}</BannerContent>
        </Banner>
      ) : null}
      <JobsPanel
        jobs={jobs.data?.rows ?? []}
        total={jobs.data?.total ?? 0}
        filters={filters}
        onFilters={changeFilters}
        sort={sort}
        order={order}
        onSort={changeSort}
        page={page}
        size={size}
        onPage={setPage}
        onSize={(next): void => {
          setSize(next)
          setPage(1)
        }}
        selected={selected}
        logs={logs.data}
        loadingLogs={logs.isLoading}
        onSelect={setSelected}
        loading={jobs.isLoading}
      />
    </FlexLayout>
  )
}
