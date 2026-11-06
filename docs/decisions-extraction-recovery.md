# Decision Register — Extraction Recovery for a Late Record URL

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Locked** | 2026-11-06 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | Recovering a deviation skipped only because its list-row record URL had not rendered yet |
| **Companions** | `docs/FR-deviations.md` (v5.28), `docs/class-design-deviations.md` (v4.11), `docs/guide-final-action.md` |

## Context

A row can appear in the Printable View before the live Lightning list has rendered its
record link. `ListPage.read()` unions printable rows with scanned links, so the first
sample can carry the key with `href=""`. The reconciler then creates the item without a
record URL and immediately queues `EXTRACT`; extraction cannot open the record and
terminates the item as `SKIPPED — no record URL on the list row`. A later valid refresh
does store the URL, but a terminal skip is never re-queued.

`Deviation-06112026-487416` hit this: its URL is now stored, but the item stayed skipped.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | On a later valid refresh, an item skipped with the exact missing-record-URL reason whose row now has an `href` returns to `PRESENT`, clears the reason, and enqueues one `EXTRACT` job. | Never retry; require the operator to delete and re-add the row. | The URL arriving is the missing input; the existing state machine already allows `SKIPPED -> PRESENT`, and `enqueue` deduplicates active jobs. | `app/pipeline/reconciler.py`, `app/core/status.py` | locked |
| D-02 | Recovery is narrow: only the shared `MISSING_RECORD_URL_REASON` skip is revived. Ambiguity and SF-error skips stay terminal. | Retry every `SKIPPED` item when any later sample arrives. | Ambiguity does not improve by refreshing; retrying it would loop forever and hide a real extraction problem. | `app/core/status.py`, `app/workflows/deviations_z02/extraction.py`, `app/pipeline/reconciler.py` | locked |
| D-03 | Recovery needs no schema, API or generated-type change; it uses the next valid list refresh and the existing EXTRACT queue. | A manual re-extract endpoint or a background sweeper. | The refresh already observes the URL, so a new surface would duplicate state the reconciler already owns. | `app/pipeline/reconciler.py` | locked |

## What stays the same

- A first-seen row still becomes `PRESENT` and gets an `EXTRACT` job immediately.
- A row that never gets a record URL stays skipped with the same reason.
- Ambiguity skips and their reasons are untouched.
- No table, column, migration, endpoint, request/response shape or generated TypeScript
  type changes.

## Amendments

None.
