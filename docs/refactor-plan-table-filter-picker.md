# Refactor Plan — Combined Table Filter Picker

| | |
|---|---|
| **Status** | BUILT |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Feature** | One searchable multiselect filter per table column, plus a fused range variant |
| **Decisions** | `docs/decisions-table-filter-picker.md` (v1, LOCKED) |

## Phases

### Phase 1 — Shared primitive

- Add `frontend/src/components/SearchSelect.tsx`: one Salt `ComboBox multiselect` with a
  controlled query, client-side option filtering by value and label, checked pills and
  the existing `onSelectionChange` contract.
- Refactor `DeckPicker.tsx` to use it, keeping its labels, Clear button, stale-key
  pruning and tests unchanged.
- Cover the primitive through the `DeckPicker` and `TableFilter` tests: typing filters
  options, checking selects, pills remove, and disabled state.

### Phase 2 — Table filter

- Replace the `Input` + `Dropdown` stack in `TableFilter.tsx` with `SearchSelect`.
- Keep `label`, `text`, `onText`, `selected`, `onSelected`, `options` and `placeholder`.
- Add `textMode?: 'filter' | 'search'`, defaulting to `filter`; search mode keeps a local
  query and clears it after a check so the option list stays usable.
- Mark fixed-option enum columns whose displayed label differs from the raw value as
  `textMode="search"`: Jobs **Status** and History **Status**. Columns whose label equals
  the raw value (`kind`, `phase`) stay in the default `filter` mode, and the History
  **SF approval** column is a date text filter, not a fixed enum.
- Add `TableFilter` tests for filter mode, search mode, pills and multiple selection.

### Phase 3 — Range filter

- Replace the stacked inputs in `TableRangeFilter.tsx` with one bordered
  `From – To` group while keeping the two labels, values and input types.
- Add the layout-only `.range-filter` rule to `index.css`; no table, data or API change.
- Add range tests for labels, values and change callbacks.

### Phase 4 — Call sites and tests

- Update `JobsPanel`, `HistoryTable` and `DevDbPage` filter tests from
  `textbox`/`<label> values` selectors to the single `combobox` and `option` roles.
- Verify every column still composes text and exact values, and that the Dev DB preview
  remains client-side.
- Check the filter row at 390, 768 and 1280 px; raise a column's default width only if
  the combined control clips.

### Phase 5 — Documentation and gates

- Bump the FR, frontend-design, class-design, data-model and API docs as listed in the
  decision register.
- Add `docs/guide-table-filter-picker.md` and update the `docs/README.md` ledger.
- Run `npm --prefix frontend run test`, `typecheck`, `lint`, `build`,
  `mypy --strict app tests` and `ruff check app/ frontend/`.

## Cutover and rollback

No data migration. The frontend swap is atomic: reverting the frontend restores the old
stacked controls, and the server contract is untouched in both directions.
