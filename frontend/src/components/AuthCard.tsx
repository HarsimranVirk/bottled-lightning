/** Session card: the only screen shown when there is no usable Salesforce session. */

import type { JSX } from 'react'
import { Button, Card, FlexLayout, H2, Text } from '@salt-ds/core'

import type { SessionView } from '../api'
import { relativeTime } from '../format'

interface Props {
  session: SessionView
  onLogin: () => void
  loggingIn: boolean
}

export function AuthCard({ session, onLogin, loggingIn }: Props): JSX.Element {
  const expired = session.state === 'expired'
  return (
    <Card className="auth-card">
      <FlexLayout direction="column" gap={3} align="start">
        <H2>{expired ? 'Salesforce session expired' : 'Log in to Salesforce'}</H2>
        <Text>
          {expired
            ? 'The saved session is no longer accepted. Log in once in the browser window; the snapshot is saved automatically and jobs resume.'
            : 'The app automates Salesforce through a real browser session. Log in once; the session is stored locally so restarts do not need it again.'}
        </Text>
        {session.savedAt ? (
          <Text color="secondary">Last login {relativeTime(session.savedAt)}</Text>
        ) : null}
        <Button appearance="bordered" sentiment="accented" onClick={onLogin} disabled={loggingIn}>
          {loggingIn ? 'Waiting for the login window…' : 'Log in'}
        </Button>
      </FlexLayout>
    </Card>
  )
}
