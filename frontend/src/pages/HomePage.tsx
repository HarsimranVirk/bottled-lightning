/** Landing page: session state, sync health and quick links. */

import type { JSX } from 'react'
import { Card, FlexLayout, H2, Spinner, Text } from '@salt-ds/core'
import { Link } from 'react-router-dom'

import { AuthCard } from '../components/AuthCard'
import { relativeTime } from '../format'
import { useLogin, useSession, useSync, useWorkers, useWorkflows } from '../queries'

export function HomePage(): JSX.Element {
  const session = useSession()
  const workflows = useWorkflows()
  const login = useLogin()
  const queue = useWorkers()
  const workflow = workflows.data?.[0]
  const sync = useSync(workflow?.name ?? null)

  if (session.isLoading || workflows.isLoading) return <Spinner />
  if (!session.data) return <Text>Session unavailable.</Text>

  return (
    <FlexLayout direction="column" gap={4}>
      {session.data.state !== 'valid' ? (
        <AuthCard session={session.data} onLogin={() => login.mutate()} loggingIn={login.isPending} />
      ) : (
        <Card>
          <FlexLayout direction="column" gap={2}>
            <H2>{workflow?.label ?? 'Workflow'}</H2>
            <Text>
              Session active ({session.data.cookies ?? 0} cookies). List synced {relativeTime(sync.data?.capturedAt)}.
            </Text>
            <Text>
              Workers: {queue.data?.inFlight ?? 0}/{queue.data?.concurrency ?? 0} busy,{' '}
              {queue.data?.counts.queued ?? 0} queued.
            </Text>
            <Link to="/deviations-z02">Open Deviations Z02</Link>
            <Link to="/jobs">Jobs</Link>
          </FlexLayout>
        </Card>
      )}
    </FlexLayout>
  )
}
