# Guide — Table UX (history links, resizable tables)

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Feature** | History object-link columns; one shared `DataTable` with resizable columns |
| **Design** | `docs/decisions-table-ux.md` (v2, LOCKED), `docs/FR-deviations.md` FR-8.11 and FR-9.20–9.24, `docs/api-deviations.md` §history, `docs/frontend-design-deviations.md` §3.5c |

## What it does

1. **History shows the five object links.** Each approved-history row now has columns for
   Opportunity, CL contract, Collateral, LMS2 CL contract and LMS2 collateral. A cell
   shows the linked object's name (e.g. `LAI-00537463`) and opens its Salesforce page in a
   new tab. A link that was never captured shows `—`.
2. **Every table is one table.** History, Jobs and the Dev DB result preview now share a
   single `DataTable`: pagination, a filter on every column, and columns you can resize.
   Widths persist per table across reloads; **Reset columns** restores the defaults.
3. **Width stays under control.** A table that is wider than its container scrolls
   sideways *inside the table*, never the page. Default widths fit 390/768/1280 except
   History at 1280, which is wider by design.

## How to use it

### Reading history links

1. Open the Z02 tab, switch to **History** (`?view=history`).
2. The five link columns sit after **SF approval**. Click a name to open that object.
3. Filter a link column like any other: type part of the name, or open the dropdown and
   tick exact names.

Equivalent request:

```bash
curl -s 'http://127.0.0.1:8765/api/deviations/history?ref=collateral:CJID-0000282798'
curl -s 'http://127.0.0.1:8765/api/deviations/history?ref_text=opportunity:PRIYANKA'
```

### Resizing a column

1. Hover the right edge of a column header; the cursor becomes a resize arrow.
2. Drag. On a keyboard, focus the edge and press ← / → (16 px steps).
3. The width is stored and restored on the next visit. **Reset columns** appears once a
   width differs from the default.
4. Below 900 px the handles are hidden and low-value columns collapse by breakpoint, as
   before.

The Dev DB result table resets widths when the query changes, because its column set is
dynamic.

## Configuration and where state lives

| Thing | Where |
|---|---|
| Column widths | browser `localStorage`, key `sf.data-table.widths.v1.<tableId>` |
| Table ids | `history`, `jobs`, `dev-<hash>` (Dev DB) |
| Link kinds | workflow `ref_kinds`: `opportunity`, `cl_contract`, `collateral`, `lms2_cl_contract`, `lms2_collateral` |
| Exact link filter | `GET …/history?ref=<kind>:<name>` |
| Contains link filter | `GET …/history?ref_text=<kind>:<text>` |

No database change, no migration, no environment variable. The links come from
`approved_deviation_refs`, which already existed; old snapshots simply lack a kind and
render `—`.

## Five most likely failure modes

1. **A table is cut off at the right and you cannot see the last columns.**
   Scroll horizontally inside the table (trackpad or shift+wheel), or press **Reset
   columns**. The page itself never scrolls sideways.
2. **A widened column is still wide tomorrow.**
   Widths persist by design. Use **Reset columns** to restore the defaults.
3. **A link filter returns nothing.**
   Exact values compare the linked object's **name** case-sensitively; contains filters
   are case-insensitive. Copy the name from the cell (or the dropdown options) rather than
   typing an id that is not shown.
4. **A cell shows `—`.**
   That object kind was never captured for this snapshot (extraction did not visit it, or
   the snapshot predates the link). Open the deviation record in Salesforce to reach it.
5. **`422 invalid_history_filter` when calling the API.**
   `ref` and `ref_text` must be `kind:value`; a value without a colon is rejected.

## Where to read more

- Decision register: `docs/decisions-table-ux.md` (D-01…D-12, locked 2026-11-05).
- Requirements: `docs/FR-deviations.md` FR-8.11, FR-9.13, FR-9.20–9.24.
- API and payloads: `docs/api-deviations.md` (`GET /api/deviations/history`).
- Component contract: `docs/frontend-design-deviations.md` §3.5c.
- Data model: `docs/data-model-deviations.md` §4.16 (no schema change).
- Screenshots: `docs/screenshots/table-ux-{390,768,1280}.png`.
