/** Home card: the addresses to open the app on this and other devices. */

import { useState } from 'react'
import type { JSX } from 'react'
import { Button, Card, FlexLayout, H3, Text } from '@salt-ds/core'

import type { NetworkView } from '../api'

interface Props {
  network: NetworkView
}

export function NetworkCard({ network }: Props): JSX.Element {
  const [copied, setCopied] = useState(false)

  async function copy(): Promise<void> {
    const url = network.lanUrl
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Card>
      <FlexLayout direction="column" gap={1}>
        <H3>Open on another device</H3>
        {network.lanEnabled && network.lanUrl ? (
          <FlexLayout gap={1} align="center" wrap>
            <Text>{network.lanUrl}</Text>
            <Button appearance="bordered" onClick={() => void copy()}>
              {copied ? 'Copied' : 'Copy link'}
            </Button>
          </FlexLayout>
        ) : (
          <Text color="secondary">
            LAN access is off. Start the app with SF_HOST=0.0.0.0 on a network this
            device can reach, then reload.
          </Text>
        )}
        <Text color="secondary">This device: {network.localUrl}</Text>
      </FlexLayout>
    </Card>
  )
}
