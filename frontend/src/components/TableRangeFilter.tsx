/**
 * Standard range table filter: one bordered From/To group for continuous columns.
 *
 * The two bounds stay separate labelled inputs so native date/number entry and keyboard
 * behaviour are unchanged; the wrapper only makes them read as one filter cell. The
 * parent owns both values and their server/client semantics. There is no checkbox list.
 */

import type { JSX } from 'react'
import { FlexLayout, Input, Text } from '@salt-ds/core'

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

/** Render the lower and upper bounds inside one visual range group. */
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
    <FlexLayout gap={0.5} align="center" className="range-filter">
      <Input
        value={from}
        inputProps={{
          'aria-label': fromLabel,
          type,
          placeholder: fromPlaceholder,
          onChange: (event) => onFrom(event.target.value),
        }}
        style={{ flex: '1 1 0', minWidth: 0 }}
      />
      <Text color="secondary" aria-hidden="true">
        –
      </Text>
      <Input
        value={to}
        inputProps={{
          'aria-label': toLabel,
          type,
          placeholder: toPlaceholder,
          onChange: (event) => onTo(event.target.value),
        }}
        style={{ flex: '1 1 0', minWidth: 0 }}
      />
    </FlexLayout>
  )
}
