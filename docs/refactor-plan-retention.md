# Refactor Plan — Retention (jobs, logs, sync runs)

| | |
|---|---|
| **Status** | Ready — executing |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Depends on** | `docs/decisions-retention.md` (v2, LOCKED 2026-11-05) |
| **Touches** | `app/core/repo/sync_runs.py`, `app/core/repo/purge.py`, `tests/test_purge.py`, `tests/test_repositories.py`, `docs/guide-retention.md`, `docs/README.md` |
| **Does not touch** | schema, API payloads, frontend, workflows, jobs/dispatcher, pipeline |

## 1. Slices

Each slice is independently green: it ships with its tests and leaves the app shippable.

### Slice 1 — `sync_runs` ring (D-01, D-02, FR-8.9, FR-11.6, I15)

`SyncRunRepository.record()` inserts the sample and, in the same transaction, deletes
everything outside the newest 20 rows per workflow. Ordered by `id DESC`, which is what
`recent(limit=20)` reads.

Files: `app/core/repo/sync_runs.py`, `tests/test_repositories.py`.

Tests:
- 25 recorded samples leave 20, and `latest()` still returns the newest;
- the cap is per workflow (two workflows keep 20 each);
- `recent()` never asks for a row the ring already deleted.

### Slice 2 — jobs and logs in the current purge (D-03, D-04, D-05, FR-8.10, FR-11.1, I13)

`PurgeRepository.current()` counts and deletes `job_logs` and `jobs` for the items in
`_purge_current`, with the terminal-status filter applied in every statement. Logs first,
then jobs, then the existing child rows and the items.

Files: `app/core/repo/purge.py`, `tests/test_purge.py`.

Tests:
- terminal `succeeded`/`failed`/`cancelled` jobs and their logs are deleted with the item;
- a `queued` job keeps its item *and* survives the purge (item-set protection);
- an active job on a *new* item is untouched;
- the dry run reports the same job/log counts as the real run and deletes nothing;
- an old item with a terminal job whose *item* is recent keeps the job.

### Slice 3 — Phase C artefacts

`docs/guide-retention.md`, ledger row in `docs/README.md` (`review` → `done` after the
walkthrough), and the live walkthrough in chat covering both flows.

## 2. Verification gates

```bash
source .venv/bin/activate
python -m unittest discover -s tests
mypy --strict app tests tools
uvx ruff check app/ tools/ tests/
npm --prefix frontend run typecheck   # unchanged, run for safety
```

No schema change means no migration test and no version bump (`app/__init__.py` untouched).

## 3. Cutover

- Deploy = restart the backend. No data backfill, no config, no frontend rebuild needed.
- The first `sync_runs.record()` after boot trims the existing backlog to 20 per workflow.
- The next manual current purge deletes jobs/logs for the items it removes.

## 4. Rollback

- Revert the commit and restart. Behaviour returns to unbounded `sync_runs` and
  jobs/logs surviving the purge.
- Rows already deleted by the ring or the purge **cannot be restored**; take a copy of
  `data/app.db` first if the job history matters.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Ring SQL deletes the newest row | Ordered by `id DESC`, the inserted row has the highest id; test asserts `latest()` is non-empty after 25 inserts |
| Purge deletes an active job | Terminal filter in the statement itself (D-04) plus the item-set exclusion; tests cover both |
| Dry-run counts disagree with the delete | Same predicate functions drive both; test compares `preview.deleted` with `real.deleted` |
| Operators lose old failure logs | Documented in FR-8.10, the register's consequences, and the guide's failure modes |
