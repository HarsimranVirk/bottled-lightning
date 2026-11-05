# Refactor Plan — Approved History & Retention

| | |
|---|---|
| **Status** | Approved for implementation |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Feature** | Segregated approved-deviation history and manual purges |
| **Companions** | `docs/FR-deviations.md`, `docs/data-model-deviations.md`, `docs/class-design-deviations.md`, `docs/api-deviations.md`, `docs/dev-tools.md` |

This is the execution order for the approved design. The requirements, schema, classes
and API shapes are defined in the companion documents; this file only sequences the work.

## Phases

### Phase 1 — Schema and snapshot repository

- Bump `SCHEMA_VERSION` to 5 and create `approved_deviations`,
  `approved_deviation_fields`, `_attributes`, `_refs`, `_edits`.
- Add the one-time backfill for current items whose latest decision is `accept`.
- Add `ApprovedDeviation` and `ApprovedHistoryRepository` (accept/refresh/remove/list/get
  plus the child readers).
- Tests: fresh schema, v4 → v5 backfill, copy fidelity, cascade on remove.

### Phase 2 — Write hooks and history read model

- Hook `WorkItemService.decide` (accept writes, reject/undo removes), `submit` (refresh),
  `Worker` (refresh after the job), and `ClosureResolver` (refresh after closure).
- Add `WorkItemService.list_history`/`get_history_item` and the
  `GET /api/deviations/history` routes.
- Keep the response shapes identical to the current `ItemsPageView`/`ItemDetailView`.
- Tests: snapshot survives deletion of `work_items`; detail still returns fields, refs,
  attributes, edits and the accept decision.

### Phase 3 — Purge service and API

- Add `PurgeRepository` and `PurgeService` with fixed `24h`/`90d` cutoffs.
- Current purge: old `work_items` plus fields/attributes/refs/decisions/edits/events,
  skipping active-job items.
- History purge: old `approved_deviations` plus children.
- Add `POST /api/dev/db/purges` with dry-run and per-table counts.
- Tests: dry run, idempotency, active-job protection, no cross-store deletion.

### Phase 4 — Frontend

- History view moves to `?view=history`, with the history list and detail endpoints.
- Deck/detail behaviour and the accept flow stay unchanged.
- Dev DB explorer gets the two maintenance buttons, dry-run dialog, acknowledgement
  checkbox and result banner.
- Regenerate `frontend/src/types.ts`.
- Tests: history query hooks, dev purge dialog, history detail has no undo action.

### Phase 5 — Verification

- `mypy --strict app tests`
- `ruff check app/ tools/ tests/`
- `python -m unittest discover -s tests`
- `npm --prefix frontend run typecheck`
- `npm --prefix frontend test -- --run`
- `npm --prefix frontend run lint`
- `npm --prefix frontend run build`

## Cutover

The migration is additive. On the first boot after deploy:

1. `Database.migrate()` creates the snapshot tables.
2. If `user_version < 5`, one transaction copies every currently accepted item into the
   snapshot store.
3. The History tab switches to the snapshot read model on the same deploy.
4. Current items are left untouched; the first manual current purge is operator-driven.

No file move, no downtime and no re-login are required.

## Rollback

- Reverting the application code is safe: the current tables and decisions are untouched.
- The new tables remain in the database but are unused by the older code; they can be
  dropped manually if desired.
- If a snapshot write fails after a decision is recorded, undo/re-accept repairs it. The
  purge actions are never part of a rollback and never run automatically.
