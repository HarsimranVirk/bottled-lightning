/** Job list with an expandable log for the selected job. */

import type { JSX } from 'react'
import { H3, Spinner, Text } from '@salt-ds/core'

import type { JobLogs, JobView } from '../api'
import { formatTime } from '../format'
import { StatusChip } from './StatusChip'

interface Props {
  jobs: JobView[]
  selected: number | null
  logs: JobLogs | undefined
  loadingLogs: boolean
  onSelect: (id: number) => void
}

export function JobsPanel({ jobs, selected, logs, loadingLogs, onSelect }: Props): JSX.Element {
  if (jobs.length === 0) {
    return <Text color="secondary">No jobs have run yet.</Text>
  }
  return (
    <div className="jobs">
      <ul className="job-list">
        {jobs.map((job) => (
          <li key={job.id} aria-selected={job.id === selected}>
            <button type="button" className="job-row" onClick={() => onSelect(job.id)}>
              <span className="mono">#{job.id}</span>
              <StatusChip status={job.status} />
              <span>{job.kind}</span>
              <span className="mono">{job.item}</span>
              <span className="muted">{formatTime(job.startedAt ?? job.createdAt)}</span>
            </button>
          </li>
        ))}
      </ul>
      {selected !== null ? (
        <section className="job-logs">
          <H3>Job #{selected}</H3>
          {loadingLogs ? <Spinner /> : null}
          <pre>{logs?.logs.join('\n') ?? ''}</pre>
          {logs?.job.error ? <Text className="reason">{logs.job.error}</Text> : null}
        </section>
      ) : null}
    </div>
  )
}
