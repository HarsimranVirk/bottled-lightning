# Decision Register — Retention (jobs, logs, sync runs)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v2 |
| **Date** | 2026-11-05 |
| **Locked** | 2026-11-05 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | `sync_runs` ring buffer; `jobs` / `job_logs` in the current purge |
| **Companions** | `docs/FR-deviations.md` (v5.22), `docs/data-model-deviations.md` (v3.5), `docs/class-design-deviations.md` (v4.6), `docs/api-deviations.md` (v2.7) |

This register is the lock record for the retention change. The reasoning lives in the
four design docs; each row here is the one-line decision, what was rejected, and what it
touches. Rows are never renumbered. A locked row is changed only by a dated amendment
(`D-xxa`) that states what it invalidates.

## Context

Two tables grow with wall-clock time rather than with work:

- `sync_runs` gains one row per refresh cycle per workflow — at the default 30 s interval
  that is ~2,880 rows/day, ~1.05M/year. Production reads only `latest()`; nothing renders
  older rows.
- `jobs` / `job_logs` grow with every extraction and submission. Terminal rows are pure
  audit; only `queued` / `running` / `blocked_auth` rows are read for correctness.

Before this change, `docs/data-model-deviations.md` §7.1 explicitly declared jobs, logs
and sync runs out of scope for both purges, and §7.3 stated that no automatic retention
loop exists.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | `sync_runs` is a bounded ring: each workflow keeps its newest 20 rows, trimmed inside `SyncRunRepository.record()` in the same transaction as the insert. | Time-based auto-trim (7 or 30 days), or a manual `SYNCS` purge scope. | A time window still permits tens of thousands of rows for a table whose only reader is `latest()`; a manual scope leaves the growth until an operator clicks, and the row has no audit value to protect. | `app/core/repo/sync_runs.py`, `data-model-deviations.md` §4.9/§7.4, `class-design-deviations.md` | locked |
| D-02 | The ring is **per workflow**, 20 rows each, ordered by `id DESC` (matching `SyncRunRepository.recent(limit=20)`). | One global 20-row cap across all workflows. | A global cap shrinks each workflow's history to 20/N and breaks the alignment between what `recent()` can return and what is retained; the banner is per workflow. | `app/core/repo/sync_runs.py` | locked |
| D-03 | `jobs` and `job_logs` join the **current** purge, tied to the purged item set (same `(workflow, item_key)` predicate), not to a separate 24 h age window. | Delete any terminal job older than 24 h regardless of its item. | An item can still be on the list (`last_seen` = today) while one of its jobs is days old; an age-based delete would destroy the audit of an item that is still actionable. | `app/core/repo/purge.py`, `maintenance.py` docs, `data-model-deviations.md` §7.1 | locked |
| D-04 | The jobs delete carries `status IN ('succeeded', 'failed', 'cancelled')` as a **local guard**, so the statement can never delete an active job even if the item-set selection, the transaction boundary, or the caller changes. | Rely solely on `_purge_current`'s active-job exclusion. | The current deferred WAL transaction already aborts the selection/delete interleaving with `SQLITE_BUSY_SNAPSHOT` (verified: the purge rolls back and returns `409 purge_failed`, deleting nothing), so the filter is not what stops that race today. It is defence in depth: it encodes invariant I13 in the destructive statement itself, keeps the dry-run count's predicate identical to the delete's, and survives a switch to autocommit, split per-table transactions, or reuse by another purge scope. | `app/core/repo/purge.py`, `tests/test_purge.py` | locked |
| D-05 | `job_logs` rows are counted and deleted **explicitly**, joined through `jobs`, before the `jobs` delete; the FK cascade remains only as a backstop. | Delete `jobs` and let `ON DELETE CASCADE` remove the logs. | The dry run must report per-table counts (the confirm dialog lists them), and the delete should use the identical predicate as the count; a cascade-only delete is invisible in the purge audit. | `app/core/repo/purge.py`, `frontend` purge dialog (no change; it iterates the counts map) | locked |
| D-06 | The current purge stays manual; the `sync_runs` ring is the **only** automatic deletion in the system. | Automatic trimming of terminal jobs and logs. | Deleting an operator's failure logs without a confirmation contradicts the retention rule; jobs only grow with actual work, so the manual 24 h item window is enough. | `AGENTS.md` retention rule, `maintenance.py` docstrings, `data-model-deviations.md` §7.3 | locked |
| D-07 | No schema migration: the ring orders by the `id` PK and the jobs purge joins on `(workflow, item_key)`, covered by the existing `jobs_item` index. Schema stays v5. | Add `sync_runs(captured_at)` and `jobs(finished_at)` indexes first. | Neither new statement filters on those columns, and the ring keeps `sync_runs` at ≤20 rows per workflow, so an index would only add write cost. | `app/db/schema.py` (unchanged), `app/db/connection.py` (unchanged) | locked |

## Consequences

- The Jobs page becomes the last 24 hours of work **as of the last current purge**. Once an
  item is purged, its job log is unrecoverable; `work_item_events` records only status
  transitions, not Salesforce detail.
- `sync_runs` history older than the newest 20 per workflow is unrecoverable. No production
  reader exists for it, so nothing user-visible is lost.
- The current purge removes the existing inconsistency where purged items left `jobs` rows
  pointing at deleted items.
- The purge stays manual: nothing about jobs disappears until an operator runs
  `POST /api/dev/db/purges` with `scope=current`.
- `data/app.db` still does not shrink on disk; both purges and the ring delete rows only.
  `VACUUM` remains out of scope (unchanged).

## Known limitations (not addressed by this change)

- **Orphan queued job.** If a submit commits *after* the current purge commits, the insert
  succeeds because `jobs` has no foreign key to `work_items`; the API returns `202`, the
  worker then fails with "cannot start". Pre-existing, and not preventable inside the
  purge — the job row does not exist when the purge deletes. A real fix must serialise
  submit against purge in `WorkItemService.submit`. D-04 does not claim to fix this.
- **Stale-snapshot 409.** The race in the opposite order makes the purge fail with
  `409 purge_failed` ("database is locked") rather than deleting anything. The operator
  must retry; the retry observes the active job and skips the item. Acceptable, and worth
  keeping in the guide's failure modes.

## Alternatives considered and not chosen

- **Do nothing.** Simplest and fully reversible, but leaves ~1M `sync_runs` rows per year
  with no reader.
- **One new `OPERATIONAL` purge scope for all three tables.** Clean, but uses one 24 h
  window for tables with very different volume and leaves the Jobs page's orphans in place
  until someone clicks.
- **Two new manual scopes (`JOBS`, `SYNCS`).** Precise, but keeps the `sync_runs` growth
  until an operator acts, and adds two more destructive buttons for data with no reader.
- **Keep only the newest `sync_runs` row.** Nothing but the banner would break, but the
  dev explorer and `recent()` would become useless; 20 costs nothing.

## Open items at lock time

- None. The three shape questions (per-workflow 20, item-tied terminal jobs, accepted
  shorter Jobs history) were answered by the user on 2026-11-05.
