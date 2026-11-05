/** Global health banner: session state and refresh validity, always visible. */

import type { JSX } from 'react'
import { Banner, BannerContent, Button } from '@salt-ds/core'
import { RefreshIcon } from '@salt-ds/icons'

import type { SessionView, SyncView } from '../api'
import { relativeTime } from '../format'

interface Props {
  session: SessionView | undefined
  sync: SyncView | null | undefined
  onLogin: () => void
  onRefresh: () => void
  refreshing: boolean
}

export function SyncBanner({ session, sync, onLogin, onRefresh, refreshing }: Props): JSX.Element | null {
  if (!session) return null

  if (session.state !== 'valid') {
    return (
      <Banner status="error">
        <BannerContent>
          Salesforce session is {session.state === 'expired' ? 'expired' : 'not set'}. Jobs are paused until a manual
          login. <Button appearance="transparent" onClick={onLogin}>Log in</Button>
        </BannerContent>
      </Banner>
    )
  }

  if (sync && !sync.valid) {
    return (
      <Banner status="warning">
        <BannerContent>
          Last refresh is untrusted ({sync.warning ?? 'header/row mismatch'}) — checked{' '}
          {relativeTime(sync.capturedAt)}. Showing the previous valid list.
          <Button appearance="transparent" onClick={onRefresh} disabled={refreshing}>
            <RefreshIcon aria-hidden /> Retry sync
          </Button>
        </BannerContent>
      </Banner>
    )
  }

  // Healthy state is quiet: the footer carries session, sync age and the version.
  return null
}
