# Refactor Plan — Table UX (history links, resizable tables)

| | |
|---|---|
| **Status** | Ready — executing |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Depends on** | `docs/decisions-table-ux.md` (v2, LOCKED 2026-11-05) |
| **Touches** | `app/api/{schemas,services}.py`, `app/api/routes/workflows.py`, `app/core/repo/approved_history.py`, `tests/`, `frontend/src/**`, `docs/guide-table-ux.md`, `docs/README.md` |
| **Does not touch** | database schema, extraction, purge, session/auth, jobs/dispatcher |

## 1. Slices

### Slice 1 — history object-link columns (D-01…D-05, FR-8.11, FR-9.21)

Backend:
- `HistoryQuery` gains `ref_text` / `ref_values` `(kind, value)` pairs; `page()` adds one
  `EXISTS` per pair against `approved_deviation_refs` (`kind`, `name`).
- `ApprovedHistoryRepository.refs_for(workflow, keys)` — one batched read per page.
- `HistoryRowView(ItemRowView)` + `HistoryPageView`; `list_history` projects refs;
  `GET /api/deviations/history` returns the new page shape and parses `ref`/`ref_text`.

Frontend:
- `HistoryFilters` gains `refText` / `refValues`; `api.ts` serialises `ref`, `ref_text`.
- `HistoryTable` adds the five columns, the five filter cells and the link cells.
- Regenerate `types.ts`; `api.history` returns `HistoryPage`.

Tests: repo filter pairs, batched refs, API row shape/params, component links and `—`.

### Slice 2 — `DataTable` (D-06…D-12, FR-9.20–9.24)

- New `frontend/src/components/DataTable.tsx`: columns contract, colgroup widths,
  drag handles, persistence, reset, pagination, filter row, container scroll.
- `HistoryTable` becomes a thin adapter over `DataTable` (keeps the five columns).
- `JobsPanel` and `DevDbPage` move onto `DataTable`.
- `index.css`: scroll container, handles, responsive hiding.
- Tests: resize persistence, reset, pagination wiring, keyboard step, render parity for
  the three callers. Screenshot check at 390/768/1280 via `/dev/states` + audit tool.

## 2. Verification gates

```bash
source .venv/bin/activate
python -m unittest discover -s tests
mypy --strict app tests tools
uvx ruff check app/ tools/ tests/
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
python tools/audit_layout.py   # page-level overflow only
```

`frontend/src/types.ts` is regenerated with `tools/export_openapi.py` +
`npm --prefix frontend run types` after the schema change.

## 3. Cutover

- Restart the backend for the API shape; rebuild the frontend for the table.
- No migration: the refs already exist in every snapshot.
- Old snapshots without a given ref render `—`; nothing is backfilled.

## 4. Rollback

- Revert the commits. The API shape reverts to `ItemsPageView`; the frontend bundling
  follows the code. No data is written by this feature, so rollback has no data cost.
- Stored column widths in `localStorage` are ignored by the old build and can be cleared
  with the Reset action after re-upgrading.

## 5. Risks

| Risk | Mitigation |
|---|---|
| History payload grows | Refs are five short rows per item; the deck payload is untouched (D-02) |
| N+1 regressions | `refs_for` is the only list read; test asserts one query shape per page |
| Resize breaks alignment | `colgroup` + `table-layout: fixed`; the filter row shares the same columns |
| Layout overflow at review widths | Container-only scroll; `audit_layout.py` checks the page |
| Slice 2 loses a filter/column | Parity tests per caller; slice 2 starts from the slice-1 History |
