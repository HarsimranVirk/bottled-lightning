# Guide — Retention (jobs, logs, sync runs)

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Feature** | Sync-run history cap; jobs/logs in the current purge |
| **Design** | `docs/decisions-retention.md` (v2, LOCKED), `docs/FR-deviations.md` FR-8.6–8.10 / FR-11.1–11.6, `docs/data-model-deviations.md` §4.7–4.9 and §7, `docs/refactor-plan-retention.md` |

## What it does

Two separate changes, both about tables that used to grow forever.

1. **Sync history is a ring.** Each workflow keeps its newest **20** `sync_runs` rows.
   Every refresh records a row and immediately deletes anything older than the 20th, in
   the same transaction. Nothing to run, no button to press. The sync banner only ever
   reads the newest row, so no screen loses anything.
2. **The current purge now takes job history with it.** When an item older than 24 hours
   is removed, its **finished** jobs (`succeeded`, `failed`, `cancelled`) and those jobs'
   log lines are removed too. Active jobs (`queued`, `running`, `blocked_auth`) are never
   deleted, and their item is never purged.

What does **not** change: the purge is still manual, still dry-run first, still fixed
cutoffs (24 h current, 90 days history), still one transaction, still idempotent.
`sessions`, `session_events` and approved history are still untouched.

## How to use it

### Sync ring

Nothing to do. It is automatic on every recorded sample.

### Purging jobs and logs

1. Open the hidden dev page: `http://127.0.0.1:8765/dev/db`.
2. Click **Purge current data**.
3. The dialog calls `POST /api/dev/db/purges` with `{"scope": "current", "dryRun": true}`
   and shows a per-table count. `jobs` and `job_logs` now appear in that table.
4. Tick **I understand this cannot be undone** and click **Purge**. The same endpoint is
   called with `"dryRun": false`.

Equivalent curl:

```bash
curl -s -X POST http://127.0.0.1:8765/api/dev/db/purges \
  -H 'content-type: application/json' \
  -d '{"scope":"current","dryRun":true}'
```

A successful response includes the new keys:

```json
{
  "scope": "current",
  "cutoff": "2026-11-04T18:20:00Z",
  "dryRun": false,
  "deleted": { "work_items": 1, "jobs": 2, "job_logs": 9, "...": 0 },
  "total": 12
}
```

## Configuration and where state lives

| Setting | Value | Where |
|---|---|---|
| `SYNC_RUNS_KEPT` | 20 rows per workflow | `app/core/repo/sync_runs.py` |
| `CURRENT_RETENTION_HOURS` | 24 | `app/maintenance.py` |
| `HISTORY_RETENTION_DAYS` | 90 | `app/maintenance.py` |

- State lives in `data/app.db` (SQLite): tables `sync_runs`, `jobs`, `job_logs`.
- No environment variables, no schema change, no migration. Schema stays v5.
- The ring is trimmed in `SyncRunRepository.record()`; the purge runs in
  `PurgeRepository.current()`.
- The dev page itself is guarded by `SF_DEV_TOOLS` (default on) and localhost-only unless
  `SF_DEV_TOOLS_ALLOW_REMOTE=1`.

## Five most likely failure modes

1. **Purge returns `409 purge_failed` with "database is locked".**
   Someone submitted or synced between the cutoffs being computed and the delete. The
   whole transaction rolled back — nothing was deleted. Run the purge again; the second
   attempt sees the new job and skips that item.

2. **The Jobs page no longer shows a failure you were investigating.**
   Expected: its item was older than 24 h and you ran the current purge, so its job and
   logs were removed. The approved-history snapshot keeps the decision, but not the job
   log. Copy `data/app.db` before purging if you need the forensic trail.

3. **A job fails with "cannot start".**
   A submit committed after the purge removed its item (the orphan-queued-job race). The
   item is gone; cancel the job, or let the list refresh re-create the item if the row
   reappears in Salesforce.

4. **The dev DB shows only 20 `sync_runs` rows.**
   By design — that is the ring, per workflow. Rows older than the 20th are not archived
   anywhere.

5. **`POST /api/dev/db/purges` returns `405 Method Not Allowed`.**
   The process serving the port is older than the code, or dev tools are off (`404` if
   disabled). Restart the backend; check `curl -s localhost:8765/openapi.json` contains
   `/api/dev/db/purges`.

## Where to read more

- Decision register: `docs/decisions-retention.md` (D-01…D-07, locked 2026-11-05).
- Requirements: `docs/FR-deviations.md` FR-8.6–8.10 and FR-11.1–11.6.
- Data model and the exact SQL: `docs/data-model-deviations.md` §4.7–4.9, §7.1, §7.4.
- Class ownership: `docs/class-design-deviations.md` (`PurgeRepository`,
  `SyncRunRepository`, invariants I13/I15).
- Execution order and rollback: `docs/refactor-plan-retention.md`.
