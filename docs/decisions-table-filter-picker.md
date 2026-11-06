# Decision Register — Combined Table Filter Picker

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Locked** | 2026-11-06 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | The shared per-column table filter: one searchable multiselect control, the text-filter semantics, and the fused range variant |
| **Companions** | `docs/FR-deviations.md` (v5.28), `docs/frontend-design-deviations.md` (v4.12), `docs/data-model-deviations.md` (v4.0), `docs/api-deviations.md` (v2.12), `docs/class-design-deviations.md` (v4.11) |

## Context

`TableFilter` currently renders two stacked controls: a text `Input` whose value is a
contains filter, and a Salt multiselect `Dropdown` whose checked values are exact filters.
The operator asked for the same single control the deck picker already uses — one text
field that opens a checkbox dropdown — and for that shape to be standard across every
table. `TableRangeFilter` is the two-input from/to variant.

This is a frontend-only change. No endpoint, repository, schema, migration or generated
TypeScript type changes; the existing server text and exact-value parameters are used
exactly as they are today.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | Every column filter is one Salt `ComboBox` with `multiselect`, replacing the stacked text `Input` plus `Dropdown`. | A fused shell around the existing two controls, or a bespoke popover. | The ComboBox is the Salt component for typeahead plus multi-selection, and its multiselect `Option` supplies the checkbox glyph. A bespoke popover breaks FR-9.14's Salt-only rule. | `frontend/src/components/TableFilter.tsx`, `frontend/src/components/SearchSelect.tsx` | locked |
| D-02 | On free-text columns, typing remains the existing contains filter and also narrows the dropdown options. | Search-only typing on every column. | Free-text columns build their options from the loaded page only, so removing the contains filter would make off-page IDs, keys, errors and object names unfindable. | `frontend/src/components/TableFilter.tsx`, `JobsPanel.tsx`, `HistoryTable.tsx`, `DevDbPage.tsx` | locked |
| D-03 | On fixed-option enum columns whose displayed label differs from the raw value, typing only narrows the dropdown until a value is checked. | Sending the typed label as a raw-value text filter. | `Implemented` filters as `completed`; `status_text=impl` matches no row. The enum option list is complete, so checking the matching option gives the same result without a false empty table. | `frontend/src/components/TableFilter.tsx`, `JobsPanel.tsx`, `HistoryTable.tsx` | locked |
| D-04 | Checked values remain exact filters: OR within a column, AND across columns, and AND with the text filter in the same column; empty selection means all. | Changing the filter algebra, or applying selected values as OR with the text filter. | The existing server and Dev DB filter behaviour is correct and already covered by tests; only the control's presentation changes. | `frontend/src/components/TableFilter.tsx`, `frontend/src/components/DevDbPage.tsx` | locked |
| D-05 | The ComboBox/query/pills behaviour is extracted from `DeckPicker` into a shared `SearchSelect` primitive; `DeckPicker` and `TableFilter` are thin wrappers. | Duplicating the ComboBox wiring in two components. | The operator asked for the same control; one primitive keeps the query, option filtering, pills and selection handling identical and tested once. `DeckPicker` behaviour is unchanged. | `frontend/src/components/SearchSelect.tsx`, `frontend/src/components/DeckPicker.tsx`, `frontend/src/components/TableFilter.tsx` | locked |
| D-06 | Options stay as they are: fixed enums where the column has them, otherwise distinct non-empty values in the loaded page/preview, sorted and capped at 100. No new fetch or endpoint for distinct values. | Loading a complete distinct-value list from the server. | That would add API surface and pagination work; the contains filter remains the way to reach values outside the loaded page. | `frontend/src/components/TableFilter.tsx`, `JobsPanel.tsx`, `HistoryTable.tsx`, `DevDbPage.tsx` | locked |
| D-07 | Range filters become one bordered From/To group inside a single filter cell, while keeping two focus stops and the native date/number input types. | A single text field that parses `from..to`, or a popover trigger. | A range has two independent bounds. A single text field loses the native date picker and adds parsing; a popover is more custom UI. The fused group reads as one cell without changing the values or labels. | `frontend/src/components/TableRangeFilter.tsx`, `frontend/src/index.css` | locked |
| D-08 | Selection is reversible by unchecking an option or removing its pill; the existing page-level **Clear filters** remains the bulk reset. Table filters add no separate Clear button. | Adding a Clear button to every filter cell. | Narrow columns (Jobs ID is 80 px) cannot fit another control, and pills plus the page-level reset already cover clearing. The deck picker keeps its own Clear because it has no page-level reset. | `frontend/src/components/TableFilter.tsx`, `frontend/src/components/DeckPicker.tsx` | locked |
| D-09 | The change adds no endpoint, query parameter, table, migration or generated TypeScript type; server-side text and exact filters keep their current parameter names and payloads. | A new filter endpoint or client-side-only duplicate filter state. | Filtering already has a working contract; this change only replaces the control that edits it. | `frontend/src/components/TableFilter.tsx`, `frontend/src/components/TableRangeFilter.tsx` | locked |

## What stays the same

- `GET /api/jobs`, `GET /api/deviations/history` and the Dev DB preview keep their
  existing query parameters and response shapes.
- The text plus exact-value algebra is unchanged, including server-side totals and later
  pages.
- Option sources, labels and the 100-option cap are unchanged.
- The deck picker's behaviour is unchanged; only its internal wiring moves to
  `SearchSelect`.
- No persisted state, table, index, migration or retention rule changes.

## Amendments

None. Amendments are appended here with a date and the files/behaviour they invalidate;
locked rows are never edited in place.
