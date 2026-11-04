# Data Model — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v1 |
| **Date** | 2026-11-04 |
| **Feature** | Loan deviations (Z02) |
| **Companions** | `docs/FR-deviations.md`, `docs/class-design-deviations.md`, `docs/api-deviations.md` |
| **Implemented by** | `app/db/schema.py`, `app/core/repo/*` |

This document is the source of truth for persisted state. If the code and this
document disagree, the document is wrong **only** until it is amended in the same
change that alters the code (see AGENTS.md, plan-mode rules).

---

## 1. Store ownership

| State | Owner | Notes |
|---|---|---|
| Items, fields, refs, jobs, logs, sync history, auth snapshots | SQLite at `settings.db_path` (`data/app.db` in a checkout, OS app-data dir when installed) | Only repositories open connections; nothing else issues SQL |
| Queue leases, dispatcher state | SQLite `jobs` | There is no authoritative in-process queue; restarting the process loses nothing |
| Browser pages, cookies in flight | Chromium context, held by `BrowserRuntime` | Never persisted directly; only the storage-state snapshot is |
| Session snapshot | SQLite `sessions` | As sensitive as a password; never logged or returned by the API |

## 2. Conventions

- **Timestamps** are ISO-8601 strings with a UTC offset (`2026-11-04T04:38:09+00:00`).
  Stored as TEXT; compared lexicographically, which is sound for this format.
- **Booleans** are INTEGER 0/1 (`present`, `valid`).
- **Workflow scoping**: every item-shaped table carries `workflow` as part of its key,
  so a second workflow shares the tables without interfering.
- **Amounts and tenure** stay TEXT exactly as SF renders them. Canonicalisation happens
  in `app/core/field.py` (`normalise`), not in the schema — stored values remain
  faithful to what the operator saw.
- **No blobs**: HTML, screenshots and page content are never stored.

## 3. Schema version and migration

- `PRAGMA user_version = 2` after `Database.migrate()`.
- **Fresh database only.** `migrate()` detects a legacy database (its `jobs` table has
  no `kind` column) and raises instead of half-applying the schema.
- Cutover has happened: `data/app.db` now holds the workflow schema. The legacy
  database was wiped, not migrated (the only valuable rows were auth snapshots, which
  one manual login re-creates).
- Cutover (refactor Phase 9) deletes the old file; there is no data migration because
  the only valuable rows are auth snapshots, which are re-created by one manual login.
- Open item **O-4** is the decision to wipe; until it is answered, nothing touches
  `data/app.db`.

## 4. Tables

### 4.1 `work_items` — one row per item (mutable)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `workflow` | TEXT | no | Workflow name (`deviations_z02`) |
| `item_key` | TEXT | no | Deviation number (`Deviation-28102026-484106`) |
| `record_url` | TEXT | yes | Record path from the list row; lets an EXTRACT job start |
| `status` | TEXT | no | `WorkItemStatus` |
| `source` | TEXT | yes | `ClosureSource` (`system` / `external`) |
| `reason` | TEXT | yes | Skip or closure reason |
| `present` | INTEGER | no | 1 when the latest *valid* refresh saw it |
| `epoch` | INTEGER | no | Presence epoch; increments when an item returns |
| `first_seen` | TEXT | no | First valid refresh that contained it |
| `last_seen` | TEXT | no | Latest valid refresh that contained it |
| `absent_since` | TEXT | yes | When absence was first observed |
| `approved_at` | TEXT | yes | Approval Date column from the printable view |
| `extracted_at` | TEXT | yes | Set when extraction completed (one-shot marker) |
| `execute_attempted_at` | TEXT | yes | Final-action click recorded |
| `execute_confirmed_at` | TEXT | yes | Final-action success observed |
| `closed_at` | TEXT | yes | Terminal timestamp |

**Key** `(workflow, item_key)`. **Index** `(workflow, status)` for the working view.

Semantics:
- Rows are never deleted by normal operation (retention pending O-6).
- `extracted_at` makes extraction one-shot; `force` or a new epoch clears it.
- Terminal status is written only by the submission pipeline / closure resolver, and
  never while a live job lease exists (enforced in `WorkItemRepository.transition`).

### 4.2 `work_item_fields` — editable values (mutable)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `workflow`, `item_key`, `field_key` | TEXT | no | Composite key; `field_key` comes from the workflow catalogue |
| `extracted` | TEXT | yes | Best-effort parse result |
| `last_synced` | TEXT | yes | Value SF showed at the last refresh |
| `proposed` | TEXT | yes | Operator edit awaiting submission |
| `applied` | TEXT | yes | Value SF accepted |
| `status` | TEXT | no | `FieldStatus`: extracted / proposed / applied / rejected |
| `updated_at` | TEXT | no | Last write |

**Precedence rule (invariant I4):** a refresh may update `last_synced` but never
`proposed`. Implemented in `FieldValueRepository.set_last_synced`.

### 4.3 `work_item_attributes` — read-only extracted values (mutable, replace-on-extract)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `workflow`, `item_key`, `name` | TEXT | no | Composite key |
| `value` | TEXT | yes | Description, `requested_roi`, `ideal_roi`, `updated_roi`, `requested_variance`, `product_type`, `record_id`, `record_url` |

Generic by design: adding a read-only value needs no schema change and cannot
accidentally become writable.

### 4.4 `work_item_refs` — links to SF objects (replace-on-extract)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `workflow`, `item_key`, `kind` | TEXT | no | Composite key; `kind` is a workflow-defined object kind |
| `name` | TEXT | no | Display id (`LAI-00533155`, `CJID-0000280688`) |
| `url` | TEXT | no | Absolute Lightning URL |

`PageRefRepository.replace` writes the whole set in one transaction, so an item never
holds a half-discovered set of links.

### 4.5 `work_item_edits` — audit (append-only)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `workflow`, `item_key`, `field_key` | TEXT | no | What was edited |
| `old_value`, `new_value` | TEXT | yes | Before / after |
| `job_id` | INTEGER | yes | Submission that carried the edit |
| `created_at` | TEXT | no | When |

### 4.6 `work_item_events` — audit (append-only)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `workflow`, `item_key` | TEXT | yes | Subject (null for process-level events) |
| `job_id` | INTEGER | yes | Related job |
| `kind` | TEXT | no | `extracted`, `skipped`, `auth_paused`, `job_succeeded`, … |
| `detail` | TEXT | yes | Human-readable reason |
| `created_at` | TEXT | no | When |

### 4.7 `jobs` — queue (mutable until terminal)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `workflow`, `item_key` | TEXT | no | Subject |
| `kind` | TEXT | no | `extract` / `submit` |
| `status` | TEXT | no | queued / running / blocked_auth / succeeded / failed / cancelled |
| `phase` | TEXT | yes | extract / apply / validate / execute |
| `attempts` | INTEGER | no | Incremented at claim time (drives retry policy) |
| `lease_owner` | TEXT | yes | `pid:slot` |
| `lease_expires_at` | TEXT | yes | Expiry; stale leases are requeued |
| `created_at`, `started_at`, `finished_at` | TEXT | — | Timeline |
| `error` | TEXT | yes | Last failure |

**Indexes:** `(status, kind, created_at)` for claiming.
**Constraint (invariant I2):**

```sql
CREATE UNIQUE INDEX jobs_active ON jobs(workflow, item_key)
    WHERE status IN ('queued', 'running', 'blocked_auth');
```

One active job per item, enforced by the database rather than by application checks.

### 4.8 `job_logs` — per-job progress (append-only)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `job_id` | INTEGER | no | FK to `jobs`, `ON DELETE CASCADE` |
| `seq` | INTEGER | no | Monotonic per job |
| `line` | TEXT | no | One log line |
| `at` | TEXT | no | When |

### 4.9 `sync_runs` — refresh history (append-only)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `workflow` | TEXT | no | Which list view |
| `captured_at` | TEXT | no | When the page was sampled |
| `header_total` | INTEGER | yes | "N items" as rendered |
| `rows_read` | INTEGER | no | Rows actually parsed |
| `valid` | INTEGER | no | 1 iff `header_total == rows_read` |
| `warning` | TEXT | yes | Human-readable mismatch |
| `added`, `updated`, `closed` | INTEGER | no | Reconciliation counters |

Invalid runs are recorded deliberately: a persistent header mismatch must stay visible.

### 4.10 `sessions` — auth snapshots (append-only, latest wins)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `org` | TEXT | yes | Org base URL at login |
| `storage_state` | TEXT | no | Playwright storage-state JSON |
| `cookie_count` | INTEGER | no | Cookies captured |
| `created_at` | TEXT | no | When |

`SessionRepository.clear()` deletes all rows (force re-login).

### 4.11 `session_events` — auth history (append-only)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `event` | TEXT | no | `login`, `expired`, `snapshot` |
| `detail` | TEXT | yes | Extra context |
| `created_at` | TEXT | no | When |

## 5. Relationships

```
work_items (workflow, item_key)
   ├── work_item_fields      (1:N, one row per catalogue field)
   ├── work_item_attributes  (1:N, read-only values)
   ├── work_item_refs        (1:N, one row per object kind)
   ├── work_item_edits       (1:N, audit)
   ├── work_item_events      (1:N, audit)
   └── jobs                  (1:N historically; at most 1 active)
              └── job_logs   (1:N)

sync_runs    (per workflow, independent history)
sessions     (latest snapshot wins)
session_events
```

There are no SQL foreign keys from the item tables (SQLite + workflow-scoped
repositories made them more friction than value); `job_logs.job_id` is the one FK, with
`ON DELETE CASCADE`.

## 6. One-shot vs mutable vs append-only

| Table | Kind | Rule |
|---|---|---|
| `work_items` | mutable | Status transitions only through `WorkItemRepository.transition` |
| `work_item_fields` | mutable | `proposed` immune to refresh; `applied` written only after a verified save |
| `work_item_attributes` | replace-on-extract | Overwritten wholesale on each extraction |
| `work_item_refs` | replace-on-extract | Replaced atomically per item |
| `jobs` | mutable until terminal | Terminal rows are history; stale leases are requeued |
| `work_item_edits`, `work_item_events`, `job_logs`, `sync_runs`, `session_events` | append-only | Never updated or deleted by normal operation |
| `sessions` | append-only | Latest row wins; `clear()` removes all |

## 7. Retention

- Closed and skipped items stay in `work_items` (O-6 decides archive vs hard delete;
  the current design keeps them for history and re-entry detection).
- Logs and events grow without bound. Acceptable for a single-operator tool; if it
  becomes a problem, prune `job_logs` for jobs older than N days in a maintenance task.

## 8. Repository ownership map

| Table | Repository |
|---|---|
| `work_items` | `WorkItemRepository` |
| `work_item_fields` | `FieldValueRepository` |
| `work_item_attributes` | `AttributeRepository` |
| `work_item_refs` | `PageRefRepository` |
| `work_item_edits` | `EditRepository` |
| `work_item_events` | `EventRepository` |
| `jobs`, `job_logs` | `JobRepository` |
| `sync_runs` | `SyncRunRepository` |
| `sessions`, `session_events` | `SessionRepository` |

No other module contains SQL. The API layer (`app/api`) talks to these repositories
through `WorkItemService`/`AdminService` and never issues SQL itself.
