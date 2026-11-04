/** Compact queue indicator for the header. */

import type { JSX } from 'react'
import type { QueueView } from '../api'

interface Props {
  queue: QueueView | undefined
}

export function QueueBar({ queue }: Props): JSX.Element | null {
  if (!queue) return null
  const queued = queue.counts.queued ?? 0
  return (
    <span className="queue-bar" aria-label="Worker queue">
      {queue.paused ? <span className="chip" data-tone="danger">paused</span> : null}
      <span>{queue.inFlight}/{queue.concurrency} workers</span>
      <span>{queued} queued</span>
    </span>
  )
}
