/** Salt status indicator + word. The label always carries the meaning, never colour alone. */

import { FlexLayout, StatusIndicator, Text } from '@salt-ds/core'

import type { DecisionKind } from '../api'
import { statusLabel, statusTone } from '../format'

interface Props {
  status: string
  labels?: Record<string, string>
}

const TONE_STATUS = {
  info: 'info',
  success: 'success',
  warning: 'warning',
  danger: 'error',
} as const

export function StatusChip({ status, labels }: Props): React.JSX.Element {
  const label = statusLabel(status, labels)
  const tone = statusTone(status)
  if (tone === 'neutral') {
    return (
      <Text color="secondary" styleAs="label">
        {label}
      </Text>
    )
  }
  return (
    <FlexLayout gap={0.5} align="center">
      <StatusIndicator status={TONE_STATUS[tone]} aria-hidden />
      <Text styleAs="label">{label}</Text>
    </FlexLayout>
  )
}

/** Review decision; Salt indicator plus the word. */
export function DecisionChip({ decision }: { decision: DecisionKind }): React.JSX.Element {
  return (
    <FlexLayout gap={0.5} align="center">
      <StatusIndicator status={decision === 'accept' ? 'success' : 'error'} aria-hidden />
      <Text styleAs="label">{decision === 'accept' ? 'Accepted' : 'Rejected'}</Text>
    </FlexLayout>
  )
}
