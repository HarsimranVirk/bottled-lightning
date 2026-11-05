/** Compact queue indicator for the header, built from Salt text and status. */

import type { JSX } from 'react'
import { FlexLayout, StatusIndicator, Text } from '@salt-ds/core'

import type { QueueView } from '../api'

interface Props {
  queue: QueueView | undefined
}

export function QueueBar({ queue }: Props): JSX.Element | null {
  if (!queue) return null
  const queued = queue.counts.queued ?? 0
  return (
    <FlexLayout gap={1} align="center" aria-label="Worker queue">
      {queue.paused ? (
        <FlexLayout gap={0.5} align="center">
          <StatusIndicator status="error" aria-hidden />
          <Text styleAs="label">paused</Text>
        </FlexLayout>
      ) : null}
      <Text color="secondary" styleAs="label">
        {queue.inFlight}/{queue.concurrency} workers
      </Text>
      <Text color="secondary" styleAs="label">
        {queued} queued
      </Text>
    </FlexLayout>
  )
}
