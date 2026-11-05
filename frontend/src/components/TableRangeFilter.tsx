/** Standard range table filter: two inputs for continuous date/number columns. */

import type { JSX } from 'react'
import { Input, StackLayout } from '@salt-ds/core'

interface Props {
  fromLabel: string
  toLabel: string
  from: string
  to: string
  onFrom: (value: string) => void
  onTo: (value: string) => void
  type?: 'text' | 'date' | 'number'
  fromPlaceholder?: string
  toPlaceholder?: string
}

export function TableRangeFilter({
  fromLabel,
  toLabel,
  from,
  to,
  onFrom,
  onTo,
  type = 'text',
  fromPlaceholder,
  toPlaceholder,
}: Props): JSX.Element {
  return (
    <StackLayout gap={0.5}>
      <Input
        value={from}
        inputProps={{
          'aria-label': fromLabel,
          type,
          placeholder: fromPlaceholder,
          onChange: (event) => onFrom(event.target.value),
        }}
      />
      <Input
        value={to}
        inputProps={{
          'aria-label': toLabel,
          type,
          placeholder: toPlaceholder,
          onChange: (event) => onTo(event.target.value),
        }}
      />
    </StackLayout>
  )
}
