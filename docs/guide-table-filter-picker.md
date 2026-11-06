# Guide — Combined Table Filters

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Feature** | One searchable multiselect filter per table column, plus a fused range variant |
| **Design** | `docs/decisions-table-filter-picker.md` (v1, LOCKED), `docs/FR-deviations.md` FR-9.18/9.19/9.21, `docs/frontend-design-deviations.md` §3.5b |

## What it does

Every table column now has one filter cell instead of a text box stacked above a separate
checkbox dropdown. The cell is a single field that is both a search box and a dropdown:

1. Click the field to open the option list. Each option carries a checkbox.
2. Check one or more options. Checked values become removable pills and filter the table
   immediately. Checking more than one value in the same column shows rows matching **any**
   of them.
3. Type to narrow the options. On free-text columns (deviation key, job ID, item, error,
   linked-object name, Dev DB column) the same text is also the column's contains filter,
   so typing narrows the rows and the options together.
4. On fixed-option enum columns whose displayed label differs from the raw value (Jobs
   **Status**, History **Status**), typing only finds the option; check it to filter.
   This avoids sending a label such as `Implemented` as a raw value the server would
   never match.
5. Remove a pill or uncheck the option to undo that value. The page-level **Clear filters**
   clears the whole filter row. There is no per-column Clear button.

Date and duration columns use the range variant: one bordered **From – To** group with
two native inputs and two focus stops. It has no checkbox list.

All filters still compose the same way: selected values are OR within a column, columns
compose with AND, and the typed text plus checked values in the same column also compose
with AND. An empty selection means every value. History and Jobs keep filtering on the
server with the same query parameters, so the total and later pages stay correct; the Dev
DB preview keeps filtering client-side over its bounded result.

## How to use it

1. Start the app as usual:

   ```bash
   source .venv/bin/activate
   python -m app.main
   ```

   For frontend development, `npm --prefix frontend run dev` proxies `/api` to
   `http://localhost:8765`.

2. Open **Deviations Z02 → History** or the Jobs panel. The filter row sits under the
   column headers.
3. Click a filter, type part of a value, then check the option you want. Use the pills to
   remove one value, or **Clear filters** to reset the row.
4. Open `/dev/db`, run a query, and use the same controls above the result columns.

No new endpoint is called. The existing requests carry the same parameters:
`GET /api/jobs`, `GET /api/deviations/history`, and the Dev DB preview call. The Dev DB
preview (`POST /api/dev/db/queries` or the page's existing query action) is unchanged.

## Configuration and state

- **No environment variables** are added.
- **No database, table, index, migration or retention change.**
- **No API or generated TypeScript type change.** Filter values live in the existing
  query/filter state (`frontend/src/queries.ts`, page components).
- Filter state is ephemeral React state and resets on reload; column widths keep their
  existing per-table persistence.
- Shared code lives in `frontend/src/components/SearchSelect.tsx` (the ComboBox),
  `TableFilter.tsx` (typing semantics), and `TableRangeFilter.tsx` (the From/To group).
  Future tables must reuse these components.

## Five likely failure modes

| Symptom | Cause | What to do |
|---|---|---|
| Typing a status label shows an empty table | The column was mistakenly left in `filter` mode, so the label went to the server as raw text | Only fixed enums with human labels use `textMode="search"`; check the column's `TableFilter` prop. |
| A value outside the loaded page is missing from the dropdown | Options come from the loaded page/preview and are capped at 100; there is no distinct-value fetch | Type the value instead: on free-text columns the text is still the contains filter. |
| Checking several values shows too many rows | Selected values are OR'd within a column by design | Remove pills until only the intended values remain, or clear the column. |
| **Clear filters** leaves text in a status field | Status fields keep their option-search text separate from the row filter | The text only narrows options and does not filter rows; clear the field manually if it is distracting. |
| The range group looks like two fields | The two bounds intentionally keep separate native inputs and focus stops | Enter the lower bound on the left and the upper bound on the right; both compose as one column filter. |

## Design references

- Requirements: `docs/FR-deviations.md` FR-9.18, FR-9.19, FR-9.21.
- Locked decisions: `docs/decisions-table-filter-picker.md` D-01–D-09.
- Frontend design: `docs/frontend-design-deviations.md` §3.5b.
- Shared component design: `docs/class-design-deviations.md` §11.4.
- No persistence change: `docs/data-model-deviations.md` §1.3.
- No API change: `docs/api-deviations.md` §5 “Table filter control (client-only)”.
- Execution order and rollback: `docs/refactor-plan-table-filter-picker.md`.
