# Refactor Plan — Extraction Recovery for a Late Record URL

| | |
|---|---|
| **Status** | BUILT |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Feature** | Retry a missing-record-URL skip when the link arrives |
| **Decisions** | `docs/decisions-extraction-recovery.md` (v1, LOCKED) |

## Phases

### Phase 1 — Shared reason

- Move the exact skip reason into `app/core/status.py` as
  `MISSING_RECORD_URL_REASON`; use it from extraction and the reconciler.

### Phase 2 — Reconciler recovery

- In `Reconciler.apply()`, after touching an existing row, detect a `SKIPPED` item whose
  reason is `MISSING_RECORD_URL_REASON` and whose current sample now has an `href`.
- Transition it to `PRESENT`, clear the reason, enqueue `EXTRACT`.
- Leave every other skip reason terminal.

### Phase 3 — Tests and docs

- Add reconciler tests for the positive recovery and for an ambiguity skip that must not
  revive.
- Add FR-3.9, update the class-design reconciler pseudocode and the operator guide.
- Run backend tests, `mypy --strict app tests` and `ruff check app/ frontend/`.

## Cutover and rollback

No migration. Restart the app to load the reconciler change; the next valid list refresh
re-queues any affected item. Reverting the code restores the terminal skip with no data
loss.
