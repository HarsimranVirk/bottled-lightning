/**
 * The one searchable multiselect used by the deck picker and every table filter.
 *
 * A single Salt `ComboBox` with `multiselect` provides both the text field and the
 * checkbox dropdown. The caller owns the query and the selected values; this component
 * only filters the options client-side (by value and label), renders the checked pills
 * and reports selection changes. It never fetches, filters table rows, or writes data.
 */

import type { CSSProperties, JSX } from 'react'
import { ComboBox, Option } from '@salt-ds/core'

export interface SearchSelectOption {
  value: string
  label: string
}

interface Props {
  /** Accessible name for both the field and the dropdown, e.g. "Filter by status". */
  label: string
  placeholder?: string
  /** Controlled display text; also narrows the visible options. */
  query: string
  onQuery: (query: string) => void
  /** Checked option values, in Salt's selection order. */
  selected: string[]
  onSelected: (values: string[]) => void
  options: SearchSelectOption[]
  disabled?: boolean
  style?: CSSProperties
}

/**
 * Render one ComboBox. The option list is filtered by the current query only; the
 * caller decides whether that query is also a table filter (`TableFilter`).
 */
export function SearchSelect({
  label,
  placeholder,
  query,
  onQuery,
  selected,
  onSelected,
  options,
  disabled = false,
  style,
}: Props): JSX.Element {
  const needle = query.trim().toLowerCase()
  const visible =
    needle === ''
      ? options
      : options.filter(
          (option) =>
            option.value.toLowerCase().includes(needle) ||
            option.label.toLowerCase().includes(needle),
        )

  // Pills must show the human label, not the raw enum value (`Implemented`, not
  // `completed`). Salt uses this formatter for the selected pills only.
  function optionLabel(value: string): string {
    return options.find((option) => option.value === value)?.label ?? value
  }

  return (
    <ComboBox
      multiselect
      inputProps={{
        'aria-label': label,
        placeholder,
        onChange: (event) => onQuery(event.target.value),
      }}
      value={query}
      valueToString={optionLabel}
      selected={selected}
      onSelectionChange={(_event, next) => onSelected(next)}
      disabled={disabled}
      style={style}
    >
      {visible.map((option) => (
        <Option key={option.value} value={option.value}>
          {option.label}
        </Option>
      ))}
    </ComboBox>
  )
}
