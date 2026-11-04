/** App-wide footer: version, quiet session/sync status, manual refresh. */

import type { JSX } from 'react'
import { Button } from '@salt-ds/core'

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
    <footer className="footer">
      <span>{version ? `bottled-lightning v${version}` : 'bottled-lightning'}</span>
      <span className="footer-status">{statusText(session, sync)}</span>
      <Button appearance="transparent" onClick={onRefresh} disabled={refreshing}>
        Refresh
      </Button>
    </footer>
  )
}
