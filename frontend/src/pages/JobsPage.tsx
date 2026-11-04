/** Jobs screen: queue history with per-job logs. */

import type { JSX } from 'react'
import { FlexLayout, H1, Spinner } from '@salt-ds/core'
import { useState } from 'react'

import { JobsPanel } from '../components/JobsPanel'
import { useJobLogs, useJobs } from '../queries'

export function JobsPage(): JSX.Element {
  const jobs = useJobs(100)
  const [selected, setSelected] = useState<number | null>(null)
  const logs = useJobLogs(selected)

  if (jobs.isLoading) return <Spinner />
  return (
    <FlexLayout direction="column" gap={3}>
      <H1>Jobs</H1>
      <JobsPanel
        jobs={jobs.data ?? []}
        selected={selected}
        logs={logs.data}
        loadingLogs={logs.isLoading}
        onSelect={setSelected}
      />
    </FlexLayout>
  )
}
