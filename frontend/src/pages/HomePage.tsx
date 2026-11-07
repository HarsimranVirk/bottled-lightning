/** Landing page: session state, sync health, LAN address, version and updates. */

import type { JSX } from 'react'
import { Card, FlexLayout, H2, Spinner, Text } from '@salt-ds/core'
import { Link } from 'react-router-dom'

import { AuthCard } from '../components/AuthCard'
import { NetworkCard } from '../components/NetworkCard'
import { UpdateCard } from '../components/UpdateCard'
import { relativeTime } from '../format'
import {
  useCheckUpdate,
  useInstallUpdate,
  useLogin,
  useNetwork,
  useSession,
  useSync,
  useUpdates,
  useVersion,
  useWorkers,
  useWorkflows,
} from '../queries'

export function HomePage(): JSX.Element {
  const session = useSession()
  const workflows = useWorkflows()
  const login = useLogin()
  const queue = useWorkers()
  const workflow = workflows.data?.[0]
  const sync = useSync(workflow?.name ?? null)
  const version = useVersion()
  const network = useNetwork()
  const updates = useUpdates()
  const install = useInstallUpdate()
  const check = useCheckUpdate()

  if (session.isLoading || workflows.isLoading) return <Spinner />
  if (!session.data) return <Text>Session unavailable.</Text>

  const counts = queue.data?.counts ?? {}
  const busy = (counts.queued ?? 0) + (counts.running ?? 0) > 0

  return (
    <FlexLayout direction="column" gap={2}>
      {session.data.state !== 'valid' ? (
        <AuthCard session={session.data} onLogin={() => login.mutate()} loggingIn={login.isPending} />
      ) : (
        <Card>
          <FlexLayout direction="column" gap={1}>
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

      {network.data ? <NetworkCard network={network.data} /> : null}

      <UpdateCard
        version={version.data?.version ?? '—'}
        update={updates.data}
        installing={install.isPending}
        busy={busy}
        checking={check.isPending}
        error={install.error instanceof Error ? install.error.message : null}
        onInstall={() => install.mutate()}
        onCheck={() => check.mutate()}
      />
    </FlexLayout>
  )
}
