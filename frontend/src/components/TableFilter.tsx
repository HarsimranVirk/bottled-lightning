/**
 * Standard per-column table filter: one searchable multiselect control.
 *
 * `SearchSelect` supplies the Salt ComboBox; this wrapper decides what typing means.
 * In `filter` mode (the default) the text is the column's contains filter and also
 * narrows the options. In `search` mode typing only narrows the options until a value is
 * checked — used by fixed enums whose human label differs from the raw value. The parent
 * owns the filter state and decides whether it filters in the browser or on the server;
 * empty `selected` means every value, and selected values within one column are OR'd.
 */

import type { JSX } from 'react'
import { useState } from 'react'

import { SearchSelect } from './SearchSelect'

export interface TableFilterOption {
  value: string
  label: string
}

interface Props {
  /** Accessible name for the text field and dropdown, e.g. "Filter by status". */
  label: string
  text: string
  onText: (text: string) => void
  selected: string[]
  onSelected: (values: string[]) => void
  options: TableFilterOption[]
  placeholder?: string
  /**
   * `filter` (default): typing is the column's contains filter and narrows the options.
   * `search`: typing only narrows the options; the checked values are the filter.
   */
  textMode?: 'filter' | 'search'
}

/** Render one ComboBox whose text either filters rows or only finds options. */
export function TableFilter({
  label,
  text,
  onText,
  selected,
  onSelected,
  options,
  placeholder,
  textMode = 'filter',
}: Props): JSX.Element {
  // Search mode keeps its own query so it never becomes a row filter.
  const [searchQuery, setSearchQuery] = useState('')
  const query = textMode === 'search' ? searchQuery : text

  function changeQuery(next: string): void {
    if (textMode === 'search') {
      setSearchQuery(next)
    } else {
      onText(next)
    }
  }

  function changeSelected(next: string[]): void {
    onSelected(next)
    // In search mode the text was only a way to reach the option; reset it so the next
    // value can be found. In filter mode the text is a filter and must stay visible.
    if (textMode === 'search') {
      setSearchQuery('')
    }
  }

  return (
    <SearchSelect
      label={label}
      placeholder={placeholder}
      query={query}
      onQuery={changeQuery}
      selected={selected}
      onSelected={changeSelected}
      options={options}
      style={{ width: '100%', minWidth: 0 }}
    />
  )
}
