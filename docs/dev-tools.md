# Dev Tools — Database Explorer

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Feature** | Dev-only SQLite explorer and exports |

The explorer is a development aid, not a product surface. It is disabled unless
`SF_DEV_TOOLS=1` is set before the backend starts, and by default it accepts only
localhost requests. It is linked from `/dev/states`, not from the main navigation.

## Enable

```bash
SF_DEV_TOOLS=1 python -m app.main
```

Then open `http://localhost:8765/dev/db`.

LAN access is deliberately off. If it is genuinely needed:

```bash
SF_DEV_TOOLS=1 SF_DEV_TOOLS_ALLOW_REMOTE=1 python -m app.main
```

The database contains the Salesforce session snapshot in `sessions`; that table is
never listed, queryable or exportable.

## Page

`/dev/db`:

- table list with row counts and columns; clicking a table fills the editor with
  `SELECT * FROM "<table>" LIMIT 100`;
- SQL editor with one read-only statement;
- results table with row count, duration and truncation flag;
- **Export CSV** and **Export Excel** buttons for the current SQL.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/dev/db/tables` | table names, columns, row counts (no `sessions`) |
| `POST` | `/api/dev/db/queries` | one read-only statement, preview rows (limit 500 by default) |
| `POST` | `/api/dev/db/exports` | the same statement as a `csv` or `xlsx` file |

All three return `404` when dev tools are disabled or the request is not localhost.

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

## Files

- `app/devtools/db.py` — read-only service, authorizer, CSV/XLSX export.
- `app/api/routes/dev.py` — `/api/dev/db/*` routes.
- `frontend/src/pages/DevDbPage.tsx` — the `/dev/db` page.
- `tests/test_devtools.py` — read-only guard, table metadata, blob, CSV/XLSX, limit.
- `tests/test_api.py` — dev route visibility and file responses.

## Dependencies

- `openpyxl` for real `.xlsx` files (runtime dependency).
- `types-openpyxl` for type checking (dev dependency).
- `httpx2` for FastAPI `TestClient` in the dev-route tests (dev dependency).
