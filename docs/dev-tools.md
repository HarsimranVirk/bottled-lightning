# Dev Tools — Database Explorer

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1.2 |
| **Date** | 2026-11-05 |
| **Feature** | Dev-only SQLite explorer and exports |

The explorer is a development aid, not a product surface. It is enabled by default but
deliberately hidden: it lives at `/dev/db` and is linked only from `/dev/states`, never
from the main navigation. By default it accepts only localhost requests.

## Access

Start the backend normally:

```bash
python -m app.main
```

Then open `http://localhost:8765/dev/db` or use the link in `/dev/states`.

To turn the explorer off on a running build:

```bash
SF_DEV_TOOLS=0 python -m app.main
```

LAN access is deliberately off. If it is genuinely needed:

```bash
SF_DEV_TOOLS_ALLOW_REMOTE=1 python -m app.main
```

The database contains the Salesforce session snapshot in `sessions`; that table is
never listed, queryable or exportable.

## Page

`/dev/db`:

- table list with row counts and columns; clicking a table fills the editor with
  `SELECT * FROM "<table>" LIMIT 100`;
- SQL editor with one read-only statement;
- results table with a per-column filter row (client-side contains match), shared
  pagination (10/25/50/100 rows), row count, duration and truncation flag;
- **Export CSV** and **Export Excel** buttons for the current SQL. Exports run the full
  query server-side, not the filtered page view;
- a **Maintenance** section with **Purge current data** and **Purge historical data**.

The preview is capped at 500 rows by default; filtering and pagination operate on that
preview. Add a `LIMIT`/`WHERE` to the SQL for a narrower or deeper result. Exports are
capped at 100,000 rows and reject a truncated result instead of writing a partial file.

## Manual purges

These are the only write actions in the explorer. Both are manual, confirmed and
server-timed; the request cannot choose a cutoff.

| Action | Scope | Cutoff | Never touches |
|---|---|---|---|
| Purge current data | `work_items` plus its fields, attributes, refs, decisions, edits and events | 24 hours | active-job items, `jobs`, `job_logs`, `sync_runs`, `sessions`, `session_events`, `approved_*` |
| Purge historical data | `approved_deviations` plus its snapshot children | 90 days | `work_items`, decisions, jobs, syncs, sessions |

Each dialog first calls the endpoint with `dryRun: true` and shows the per-table counts.
Confirming runs one transaction. A second run with the same cutoff deletes zero rows.
The current purge measures age from the work item's latest activity
(`closed_at`/`last_seen`/`first_seen`) and skips any item with a queued, running or
blocked-auth job. Deleting the item's old decisions is deliberate: a deviation that
returns later must not inherit a stale accept.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/dev/db/tables` | table names, columns, row counts (no `sessions`) |
| `POST` | `/api/dev/db/queries` | one read-only statement, preview rows (limit 500 by default) |
| `POST` | `/api/dev/db/exports` | the same statement as a `csv` or `xlsx` file |
| `POST` | `/api/dev/db/purges` | manual current (24 h) or history (90 d) purge |

All four return `404` when dev tools are disabled or the request is not localhost.

### Query request

```json
{ "sql": "SELECT * FROM work_items LIMIT 50", "limit": 500 }
```

### Query response

```json
{
  "columns": ["work_item_key"],
  "rows": [["Deviation-03112026-486382"]],
  "rowCount": 1,
  "truncated": false,
  "durationMs": 3
}
```

### Export request

```json
{ "sql": "SELECT * FROM work_items", "format": "xlsx" }
```

The response is an attachment named
`bottled-lightning-export-YYYYMMDD-HHMMSS.csv` or `.xlsx`.

### Purge request

```json
{ "scope": "current", "dryRun": true }
```

Response: `{ scope, cutoff, dryRun, deleted: { table: count }, total }`. A real run
returns the same shape with `dryRun: false`. `scope` is `current` or `history`; any other
value is a `422`. The route returns `404` under the same dev/localhost guard as the
read-only explorer.

## Safety rules

- A separate **read-only** SQLite connection (`mode=ro`, `PRAGMA query_only=ON`).
- An SQLite authorizer denies every write/DDL action, `PRAGMA`, `ATTACH`, `DETACH`,
  `TRANSACTION`, `SAVEPOINT`, and any read of the `sessions` table.
- Dangerous SQL functions (`load_extension`, `writefile`, `readfile`, `edit`,
  `fts3_tokenizer`) are denied.
- One statement per request; Python's `sqlite3` rejects multiple statements.
- A progress handler aborts a query after roughly 2 seconds.
- Preview is capped at 5,000 rows; export is capped at 100,000 rows. A truncated
  export fails with a clear "add a LIMIT" message instead of silently writing a partial
  file.
- BLOB values become `<blob N bytes>`, never raw material.
- The token-bearing `sessions` table is excluded from the table list and blocked by the
  authorizer; `session_events` is allowed because it contains only event text.
- The purge service uses a separate writable connection and never touches `sessions`.
  Both scopes are fixed in code; no user-supplied SQL or cutoff reaches them.
- A purge is one transaction, so a failure rolls back every table. The confirmation
  dialog is a safety affordance, not the security boundary — the localhost guard is.

## Files

- `app/devtools/db.py` — read-only service, authorizer, CSV/XLSX export.
- `app/core/repo/approved_history.py` — approved snapshot writer/reader.
- `app/core/repo/purge.py` — destructive SQL for both scopes.
- `app/maintenance.py` — `PurgeService`, retention constants and result type.
- `app/api/routes/dev.py` — `/api/dev/db/*` routes, including `/purges`.
- `frontend/src/pages/DevDbPage.tsx` — the `/dev/db` page and maintenance dialogs.
- `tests/test_devtools.py` — read-only guard, table metadata, blob, CSV/XLSX, limit.
- `tests/test_purge.py` — both scopes, active-job protection, dry run, idempotency.
- `tests/test_approved_history.py` — snapshot write/refresh/remove/read and backfill.
- `tests/test_api.py` — dev route visibility, history endpoints and file responses.

## Dependencies

- `openpyxl` for real `.xlsx` files (runtime dependency).
- `types-openpyxl` for type checking (dev dependency).
- `httpx2` for FastAPI `TestClient` in the dev-route tests (dev dependency).
