/**
 * Standard per-column table filter: a text input plus a multiselect checkbox dropdown.
 *
 * The parent owns the filter state and decides whether the filter is applied in the
 * browser (bounded previews) or sent to the server. Empty `selected` means every value;
 * selected values within one column are OR'd by the caller.
 */

import type { JSX } from 'react'
import { Dropdown, Input, Option, StackLayout } from '@salt-ds/core'

export interface TableFilterOption {
  value: string
  label: string
}

interface Props {
  /** Accessible name for the text input, e.g. "Filter by status". */
  label: string
  text: string
  onText: (text: string) => void
  selected: string[]
  onSelected: (values: string[]) => void
  options: TableFilterOption[]
  placeholder?: string
  inputType?: 'text' | 'date' | 'number'
}

export function TableFilter({
  label,
  text,
  onText,
  selected,
  onSelected,
  options,
  placeholder,
  inputType = 'text',
}: Props): JSX.Element {
  return (
    <StackLayout gap={0.5}>
      <Input
        value={text}
        inputProps={{
          'aria-label': label,
          type: inputType,
          placeholder,
          onChange: (event) => onText(event.target.value),
        }}
      />
      <Dropdown
        aria-label={`${label} values`}
        multiselect
        selected={selected}
        value={selected.length === 0 ? 'All' : `${selected.length} selected`}
        onSelectionChange={(_event, next) => onSelected(next)}
        disabled={options.length === 0}
        style={{ width: '100%', minWidth: 80 }}
      >
        {options.map((option) => (
          <Option key={option.value} value={option.value}>
            {option.label}
          </Option>
        ))}
      </Dropdown>
    </StackLayout>
  )
}
