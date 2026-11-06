/** App-wide footer: version, quiet session/sync status, manual refresh. */

import type { JSX } from 'react'
import { Button, Divider, FlexLayout, Text } from '@salt-ds/core'
import { RefreshIcon } from '@salt-ds/icons'

import type { SessionView, SyncView } from '../api'
import { relativeTime } from '../format'

interface Props {
  version: string | undefined
  session: SessionView | undefined
  sync: SyncView | null | undefined
  onRefresh: () => void
  refreshing: boolean
}

function statusText(session: SessionView | undefined, sync: SyncView | null | undefined): string {
  if (session === undefined) return 'connecting…'
  if (session.state !== 'valid') return `Session ${session.state}`
  if (sync && !sync.valid) return 'Session active · last refresh untrusted'
  return `Session active · synced ${relativeTime(sync?.capturedAt)} · ${sync?.rowsRead ?? 0} rows`
}

export function AppFooter({
  version,
  session,
  sync,
  onRefresh,
  refreshing,
}: Props): JSX.Element {
  return (
    <footer className="app-footer">
      <Divider />
      <FlexLayout justify="space-between" align="center" gap={2} wrap className="app-footer-content">
        <Text styleAs="label">{version ? `bottled-lightning v${version}` : 'bottled-lightning'}</Text>
        <FlexLayout gap={2} align="center" wrap>
          <Text styleAs="label" color="secondary">
            {statusText(session, sync)}
          </Text>
          <Button
            appearance="transparent"
            onClick={onRefresh}
            disabled={refreshing || session?.state !== 'valid'}
          >
            <RefreshIcon aria-hidden /> Sync now
          </Button>
        </FlexLayout>
      </FlexLayout>
    </footer>
  )
}
