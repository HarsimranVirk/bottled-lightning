/**
 * Search-and-pin control for the review deck (FR-10.12).
 *
 * The shared `SearchSelect` supplies one Salt `ComboBox` with `multiselect`, so the same
 * element is a text field and a dropdown and Salt's multiselect `Option` renders the
 * checkbox glyph. Typing filters the options by deviation key on the client, checking a
 * row reports the new key list to the parent, and checked keys render as removable pills.
 * The parent owns the pin state and does the reordering — this component never fetches,
 * decides, or writes anything.
 */

import type { JSX } from 'react'
import { Button, FlexLayout, StackLayout, Text } from '@salt-ds/core'
import { useState } from 'react'

import type { ItemRow } from '../api'
import { SearchSelect } from './SearchSelect'

interface Props {
  /** The deck rows that may be pinned; the parent passes natural deck order. */
  rows: ItemRow[]
  /** Keys currently pinned, in check order. */
  selected: string[]
  /** Called with the full key list after a check, uncheck, pill removal or Clear. */
  onSelected: (keys: string[]) => void
}

export function DeckPicker({ rows, selected, onSelected }: Props): JSX.Element {
  const [query, setQuery] = useState('')
  const keySet = new Set(rows.map((row) => row.key))
  // A pin whose row has already left the deck must not keep a phantom pill on screen.
  const liveSelected = selected.filter((key) => keySet.has(key))

  /**
   * Apply a new selection and clear the search text. Clearing is the standard ComboBox
   * behaviour after a choice and keeps the next search predictable; pills remain the
   * visible record of what is pinned.
   */
  function change(next: string[]): void {
    onSelected(next)
    setQuery('')
  }

  /** Remove every pin and reset the search field. */
  function clear(): void {
    change([])
  }

  return (
    <StackLayout gap={0.5} className="deck-bar">
      <Text color="secondary" styleAs="label">
        Find &amp; pin deviations
      </Text>
      <FlexLayout gap={1} align="center" wrap>
        <SearchSelect
          label="Find and pin deviations"
          placeholder="Type a deviation number"
          query={query}
          onQuery={setQuery}
          selected={liveSelected}
          onSelected={change}
          options={rows.map((row) => ({ value: row.key, label: row.key }))}
          disabled={rows.length === 0}
          style={{ flex: '1 1 320px', minWidth: 220 }}
        />
        <Button
          appearance="bordered"
          disabled={liveSelected.length === 0}
          onClick={clear}
        >
          Clear
        </Button>
      </FlexLayout>
    </StackLayout>
  )
}
