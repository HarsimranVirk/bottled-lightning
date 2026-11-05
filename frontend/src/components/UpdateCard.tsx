/** Home card: the running version and the update install action. */

import type { JSX } from 'react'
import { Button, Card, FlexLayout, H3, Spinner, Text } from '@salt-ds/core'

import type { UpdateStatus } from '../api'

interface Props {
  version: string
  update: UpdateStatus | undefined
  installing: boolean
  busy: boolean
  error?: string | null
  onInstall: () => void
}

export function UpdateCard({
  version,
  update,
  installing,
  busy,
  error = null,
  onInstall,
}: Props): JSX.Element {
  const installingNow = installing || update?.status === 'installing'
  const available = update?.updateAvailable === true
  const failed = update?.status === 'failed'

  return (
    <Card>
      <FlexLayout direction="column" gap={1}>
        <H3>Version {version}</H3>
        {installingNow ? (
          <FlexLayout gap={1} align="center">
            <Spinner size="small" />
            <Text>
              Installing {update?.latest ?? 'the update'}… the app will restart.
            </Text>
          </FlexLayout>
        ) : available ? (
          <FlexLayout gap={1} align="center" wrap>
            <Text>Update {update?.latest ?? ''} is available.</Text>
            <Button appearance="bordered" onClick={onInstall} disabled={busy}>
              Install update
            </Button>
            {busy ? (
              <Text color="secondary">Wait for the running jobs to finish.</Text>
            ) : null}
          </FlexLayout>
        ) : (
          <Text color="secondary">
            {failed
              ? `Update check failed: ${update?.error ?? 'unknown error'}`
              : 'Up to date.'}
          </Text>
        )}
        {error ? <Text color="secondary">{error}</Text> : null}
      </FlexLayout>
    </Card>
  )
}
