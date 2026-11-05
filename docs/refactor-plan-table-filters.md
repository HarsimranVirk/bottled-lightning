# Refactor Plan — Standard Table Filters

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Feature** | Shared text + multiselect table filters across every table |
| **Companions** | `docs/FR-deviations.md`, `docs/api-deviations.md`, `docs/frontend-design-deviations.md`, `docs/class-design-deviations.md` |

## Phases

### Phase 1 — Shared components

- Add `frontend/src/components/TableFilter.tsx` (text input + Salt multiselect
  `Dropdown` with checkboxes) and `TableRangeFilter.tsx` (two inputs for ranges).
- Add component tests for selection, clearing, trigger text and text changes.

### Phase 2 — Dev DB results

- Replace the text-only filter row with `TableFilter` on every column.
- Build distinct option lists from the 500-row preview, sorted and capped.
- Apply text and selected values together; keep filtering client-side and exports
  unchanged.
- Update page tests.

### Phase 3 — Jobs (server-side)

- Extend `JobQuery` with repeated enum sets, exact `id_in`/`item_in`/`error_in` sets and
  enum text contains filters.
- Change the jobs route/service params to repeated lists; keep single values working.
- Update `JobFilters`, `jobsQuery` and `JobsPanel` to use `TableFilter` and
  `TableRangeFilter`; include values from the loaded page as options for free-text
  columns.
- Add repository/API tests for multi-value and exact filters.

### Phase 4 — History (server-side)

- Add `HistoryQuery` and the history route parameters: key/status/approval contains and
  exact sets, a decided date range, and repeated field text/value filters.
- Add a filtering row to `HistoryTable` using the shared components; build options from
  the current page and send every filter to the server.
- Replace the global history search state with the filter object; reset to page 1 on any
  change.
- Add repository/API/UI tests.

### Phase 5 — Documentation and verification

- Update `AGENTS.md` with the mandatory pattern for future tables.
- Update FR, API, frontend, class-design and data-model docs.
- Run mypy, ruff, backend tests, frontend typecheck/lint/tests/build and regenerate the
  OpenAPI types.

## Cutover and rollback

No schema change and no data migration. The filters are additive query parameters, and
single-value jobs parameters keep working. Reverting the frontend restores the old filter
cells; the extra API parameters are ignored by older clients.
