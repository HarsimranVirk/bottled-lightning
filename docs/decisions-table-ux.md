# Decision Register — Table UX (history links, resizable tables)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v2 |
| **Date** | 2026-11-05 |
| **Locked** | 2026-11-05 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | History object-link columns; one generic table component; pagination/filter/resize rules |
| **Companions** | `docs/FR-deviations.md` (v5.23), `docs/dev-tools.md` (v1.4), `docs/data-model-deviations.md` (v3.6), `docs/api-deviations.md` (v2.8), `docs/class-design-deviations.md` (v4.7), `docs/frontend-design-deviations.md` (v4.8) |

This register locks the combined change. The two slices ship together under one feature
because the second slice rewrites the table the first one extends.

## Context

The History table shows one link (the deviation record) and every catalogue field. The
approved snapshot already stores five object links per item, but the list does not expose
them; only the detail drawer does. Separately, the three real tables (History, Jobs, Dev
DB) have no column resizing, and History is about to grow from 8 to 13 columns, which
cannot fit 1280 px.

The user's standing rule: every table is paginated, filterable on every column, and has
resizable columns. The purpose is controlled width, not the illusion that a table can
never overflow.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | History row links are read from the existing `approved_deviation_refs` snapshot; no schema, extraction or re-snapshot change. | Denormalise five URL/name columns onto `approved_deviations`. | The refs already exist for every snapshot and are kept current by the same refresh path; a second copy would be a second source of truth. | `app/core/repo/approved_history.py` | locked |
| D-02 | History gets a dedicated `HistoryRowView` / `HistoryPageView` carrying `refs`; the shared `ItemRowView` / `ItemsPageView` is unchanged. | Add `refs` to the shared row shape used by the deck. | The deck endpoint is polled every 10 s and never renders refs in a list; a shared field would force a per-row read there and be permanently empty. | `app/api/schemas.py`, `app/api/services.py` | locked |
| D-03 | Refs for a page are fetched with one batched query (`refs_for(workflow, keys)`), not one query per row. | N+1 calls to the existing `refs(workflow, key)`. | A 25-row page would otherwise issue 25 extra queries per request; the page is paged and re-fetched on filter changes. | `app/core/repo/approved_history.py` | locked |
| D-04 | Each of the five link columns shows the ref `name` (`LAI-00533155`, `CJID-0000280688`) as the link text to its `url`; a missing kind renders `—`. | Generic “Open” text, or hiding a cell when the ref is absent. | The identifier is what the operator recognises and copies; a fixed five-column set must not shift between rows or pages. | `frontend/src/components/HistoryTable.tsx` | locked |
| D-05 | Link columns use the standard two-filter pair on the ref name: `ref=kind:value` (exact) and `ref_text=kind:text` (contains), each pair an `EXISTS`, AND across pairs. | No filter on link columns. | The standing rule is a filter on every column; refs are searchable identifiers, so the same text+multiselect pattern applies with no new UI concept. | `app/core/repo/approved_history.py`, `app/api/routes/workflows.py`, `frontend/src/queries.ts` | locked |
| D-06 | One generic `DataTable` component replaces the bespoke History, Jobs and Dev DB tables (T2). | T1 hook + per-table primitives; native CSS `resize`; a third-party table library. | The user chose one implementation so pagination, filters, widths and scrolling cannot drift; CSS resize has no persistence/alignment/accessibility; a library duplicates Salt. | `frontend/src/components/DataTable.tsx`, `HistoryTable.tsx`, `JobsPanel.tsx`, `DevDbPage.tsx` | locked |
| D-07 | Resizing uses a `<colgroup>`, `table-layout: fixed`, pointer drag handles in the header, 80 px minimum, ±16 px arrow keys, `role="separator"`, hidden below 900 px. | Resizing the `TH` element itself; `table-layout: auto`. | `colgroup` is the only way to keep the header row, the filter row and the body aligned; auto layout ignores explicit widths. | `frontend/src/components/DataTable.tsx`, `index.css` | locked |
| D-08 | Widths persist per table id in `localStorage` (`sf.data-table.widths.v1.*`), validated on read, with a Reset action. | Session-only widths; server-side persistence. | Reloading must not undo the operator's layout; the app has no user accounts and this is presentation state, not domain data. | `frontend/src/components/DataTable.tsx` | locked |
| D-09 | Tables scroll horizontally inside `TableContainer`; FR-9.13 is amended to “default widths fit at 390/768/1280; a resized table, and History with its 13 default columns at 1280, may scroll”. | Forbidding scroll; hiding requested columns below 1280. | 13 columns cannot fit 1280 and the five link columns were explicitly requested; a scroll container is the only honest way to keep them. | `FR-deviations.md` FR-9.13, `index.css` | locked |
| D-10 | Every real table is paginated and filterable on every column; the Dev DB preview keeps client-side pagination over its capped result. | Server-side pagination for arbitrary read-only SQL. | There is no stable cursor for an arbitrary query; the result cap plus CSV/XLSX export is the documented escape hatch, and the preview already filters every column. | `dev-tools.md`, `frontend-design-deviations.md` | locked |
| D-11 | Pagination markup lives in `DataTable`, not in each caller. | Each table keeps its own `<Pagination>` wiring. | One implementation is the point of T2; callers pass `page/size/total/onPage/onSize` and nothing else. | `frontend/src/components/DataTable.tsx` | locked |
| D-12 | Slice order: history link columns first, then the `DataTable` migration. | Primitive first, then columns. | The user asked for the visible feature first. The cost is that History is edited twice (slice 1 adds columns to the bespoke table; slice 2 moves it onto `DataTable`). | `refactor-plan-table-ux.md` | locked |

## Consequences

- History will need horizontal scrolling at 1280 px once the five columns land. FR-9.13 is
  relaxed to “fits by default”, not “never scrolls”.
- Jobs and Dev DB will look slightly different: fixed column layout, visible drag handles
  at ≥900 px, a Reset action, and a scroll container.
- History is edited in two slices; the second slice must preserve the five columns and
  their filters exactly.
- No database, extraction, purge or API-breaking change. `types.ts` is regenerated.
- The Dev DB sidebar, the purge-count dialog table and the review deck are not tables for
  this rule and are out of scope.

## Open items at lock time

- None. Layout (five columns), implementation (T2), overflow (scroll allowed), sequencing
  (links first) and the Dev DB carve-out (keep the capped preview) were answered by the
  user on 2026-11-05.
