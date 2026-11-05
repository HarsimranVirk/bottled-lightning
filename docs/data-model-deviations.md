# Data Model — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v3.7 |
| **Date** | 2026-11-05 |
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
| Items, fields, refs, review decisions, jobs, logs, sync history, auth snapshots | SQLite at `settings.db_path` (`data/app.db` in a checkout, OS app-data dir when installed) | Only repositories open connections; nothing else issues SQL |
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
- **Table filters are read-only query parameters.** The standard text + checkbox
  filters add no columns and no tables; Jobs and History build SQL predicates from their
  optional parameters, while the Dev DB filters its bounded preview in the browser.

## 3. Schema version and migration

- `PRAGMA user_version = 5` after `Database.migrate()`.
- v3 is additive: `item_decisions` (4.12) is created with `CREATE TABLE IF NOT EXISTS`
  on the next boot. No backfill — every existing item is simply undecided.
- v4 is additive: indexes for the jobs table (`item_key`, `started_at`) support the
  new filters. No column changes; duration stays derived from `started_at`/`finished_at`.
- v5 is additive: the `approved_deviations` snapshot tables (4.13–4.17). On the first
  boot from an older schema, `Database.migrate()` backfills a snapshot for every current
  item whose latest `item_decisions` row is `accept`. The backfill is one transaction and
  is skipped once `user_version` is 5.
- **Fresh database only.** `migrate()` detects a legacy database (its `jobs` table has
  no `kind` column) and raises instead of half-applying the schema.
- Cutover has happened: `data/app.db` now holds the workflow schema. The legacy
  database was wiped, not migrated (the only valuable rows were auth snapshots, which
  one manual login re-creates). O-4 is resolved.

## 4. Tables

### 4.1 `work_items` — one row per item (mutable)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `workflow` | TEXT | no | Workflow name (`deviations_z02`) |
| `item_key` | TEXT | no | Deviation number (`Deviation-28102026-484106`) |
| `record_url` | TEXT | yes | Absolute SF record URL from the list row; lets an EXTRACT job start |
| `status` | TEXT | no | `WorkItemStatus` |
| `source` | TEXT | yes | `ClosureSource` (`system` / `external`) |
| `reason` | TEXT | yes | Skip or closure reason |
| `present` | INTEGER | no | 1 when the latest *valid* refresh saw it |
| `epoch` | INTEGER | no | Presence epoch; increments when an item returns |
| `first_seen` | TEXT | no | First valid refresh that contained it |
| `last_seen` | TEXT | no | Latest valid refresh that contained it |
| `absent_since` | TEXT | yes | When absence was first observed |
| `approved_at` | TEXT | yes | Approval Date from the printable view; refreshed on every valid sync, never cleared |
| `extracted_at` | TEXT | yes | Set when extraction completed (one-shot marker) |
| `execute_attempted_at` | TEXT | yes | Final-action click recorded |
| `execute_confirmed_at` | TEXT | yes | Final-action success observed |
| `closed_at` | TEXT | yes | Terminal timestamp |

**Key** `(workflow, item_key)`. **Index** `(workflow, status)` for the working view.

**Final-action timestamps.** `execute_attempted_at` is written immediately before the
Implement click and `execute_confirmed_at` only after the `Implemented__c` tick is
observed. The closure resolver turns them into `COMPLETED`/`system` (confirmed) or
`COMPLETED`/`system` with `implement_unconfirmed` (attempted only); neither set means
`CLOSED`/`external`. The submit job cannot write `COMPLETED`/`CLOSED` itself while it
holds the lease.

Semantics:
- Rows are never deleted by normal operation; the manual current purge (7.1) removes
  items whose latest activity is older than 24 hours.
- `extracted_at` makes extraction one-shot; `force` or a new epoch clears it.
- Terminal status is written only by the submission pipeline / closure resolver, and
  never while a live job lease exists (enforced in `WorkItemRepository.transition`).

### 4.2 `work_item_fields` — editable values (mutable)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `workflow`, `item_key`, `field_key` | TEXT | no | Composite key; `field_key` comes from the workflow catalogue |
| `extracted` | TEXT | yes | Best-effort parse result; `NULL` when the description value did not change or was not found |
| `last_synced` | TEXT | yes | Value SF showed at the last refresh |
| `proposed` | TEXT | yes | Operator edit awaiting submission; `NULL` or empty means no update |
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

Rows are written by `WorkItemService.submit` at the moment the `SUBMIT` job is
enqueued: `old_value` is the last-known value (`last_synced`, else `extracted`) and
`new_value` is the proposed value. Writing the audit before the browser work means a
failed job still leaves the operator's intent on record (FR-5.3). The **actual** value
read from Salesforce immediately before the write is recorded separately in the
`submit_precheck` event and the job log, so the two are not confused: `old_value` is the
operator-facing snapshot, while the event is the verified pre-write value.

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

**Indexes:** `(status, kind, created_at)` for claiming; `(item_key)` and
`(started_at)` for the jobs table's filters.
**Duration** is never stored: it is `finished_at - started_at`, or `now - started_at`
while a job is running. Storing it would create a second source of truth.
**Constraint (invariant I2):**

```sql
CREATE UNIQUE INDEX jobs_active ON jobs(workflow, item_key)
    WHERE status IN ('queued', 'running', 'blocked_auth');
```

One active job per item, enforced by the database rather than by application checks.
**Retention:** terminal rows are deleted by the current purge when their item is purged
(§7.1). `queued`, `running` and `blocked_auth` rows are never deleted, because the queue,
the lease check and the purge's own protection filter read them.

### 4.8 `job_logs` — per-job progress (audit, deleted with its job)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `job_id` | INTEGER | no | FK to `jobs`, `ON DELETE CASCADE` |
| `seq` | INTEGER | no | Monotonic per job |
| `line` | TEXT | no | One log line |
| `at` | TEXT | no | When |

**Retention:** rows follow their job. The current purge deletes them explicitly (joined
through `jobs`) before deleting the job rows; the `ON DELETE CASCADE` remains as a
backstop, not as the primary path.

### 4.9 `sync_runs` — refresh history (bounded ring)

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
**Retention:** a bounded ring — each workflow keeps its 20 newest rows, pruned in the same
transaction as the insert (§7.4). The table is never unbounded.

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

### 4.12 `item_decisions` — review decisions (append-only, latest wins)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | PK; the highest id for an item is its current decision |
| `workflow`, `item_key` | TEXT | no | Subject, workflow-scoped |
| `decision` | TEXT | no | `accept`, `reject` or `pending` (undo) |
| `reason` | TEXT | yes | Optional operator note (typically on reject) |
| `created_at` | TEXT | no | When the decision was recorded |

**Index** `(workflow, item_key, id DESC)` for the latest-row lookup.

Semantics:
- Append-only. Undo writes `pending`; nothing is updated or deleted, so the audit keeps
  both the original decision and the reversal.
- A reader takes the row with the highest `id` per item; no row means undecided.
- The table never changes `work_items.status` and never triggers a job. Accept/reject is
  a review decision, not a pipeline transition (FR-10.2).
- Decisions survive refresh, extraction retries, and presence epochs; they are cleared
  only by an explicit undo or by the current purge when their item is removed. This is
  deliberate: a refresh must not resurrect a card the operator already dismissed, and a
  purged item must not return with a stale accept.

### 4.13 `approved_deviations` — approved-history parent (snapshot)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `workflow`, `item_key` | TEXT | no | Primary key; one snapshot per item |
| `epoch` | INTEGER | no | Presence epoch at snapshot time |
| `status` | TEXT | no | `WorkItemStatus` at snapshot time |
| `source` | TEXT | yes | `ClosureSource` if terminal |
| `present` | INTEGER | no | Presence at snapshot time |
| `record_url` | TEXT | yes | SF record URL |
| `approved_at` | TEXT | yes | Approval Date shown in SF |
| `reason` | TEXT | yes | Item reason at snapshot time |
| `decided_at` | TEXT | no | When the operator accepted; history sort key |
| `decision_reason` | TEXT | yes | Optional note on the accept |
| `snapshot_at` | TEXT | no | Last snapshot refresh |

**Indexes** `(decided_at)` for the history purge and `(workflow, decided_at DESC)` for
the newest-first history page.

The parent row is written on accept and refreshed on submit/closure. Re-accepting the
same item replaces its snapshot (same primary key); undoing or rejecting removes it. It
is copied, not derived at read time, so a current-data purge cannot erase it.

### 4.14 `approved_deviation_fields` — accepted field values (snapshot)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `workflow`, `item_key`, `field_key` | TEXT | no | Composite key |
| `extracted`, `last_synced`, `proposed`, `applied` | TEXT | yes | Same meaning as 4.2 |
| `status` | TEXT | no | `FieldStatus` |
| `updated_at` | TEXT | no | Copied from the current field row |

Foreign key to `approved_deviations` with `ON DELETE CASCADE`.

### 4.15 `approved_deviation_attributes` — context values (snapshot)

Same shape as 4.3 (`workflow`, `item_key`, `name`, `value`), with a cascading foreign
key to the parent.

### 4.16 `approved_deviation_refs` — object links (snapshot)

Same shape as 4.4 (`workflow`, `item_key`, `kind`, `name`, `url`), with a cascading
foreign key to the parent.

**History list reads** use one batch query per page —
`WHERE workflow = ? AND item_key IN (…)` — served by the `(workflow, item_key, kind)`
primary-key prefix. No column, index or migration is added for the five history link
columns; the rows already exist and are copied with the snapshot, so list and detail read
the same data.

### 4.17 `approved_deviation_edits` — submitted edits (snapshot)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | PK |
| `workflow`, `item_key`, `field_key` | TEXT | no | Subject |
| `old_value`, `new_value` | TEXT | yes | Before / after |
| `created_at` | TEXT | no | Original edit timestamp |

Cascades with the parent. The snapshot is replaced as a whole on accept/refresh; edits
are never updated in place.

## 5. Relationships

```
work_items (workflow, item_key)
   ├── work_item_fields      (1:N, one row per catalogue field)
   ├── work_item_attributes  (1:N, read-only values)
   ├── work_item_refs        (1:N, one row per object kind)
   ├── work_item_edits       (1:N, audit)
   ├── work_item_events      (1:N, audit)
   ├── item_decisions        (1:N, audit; newest row is current)
   └── jobs                  (1:N historically; at most 1 active)
              └── job_logs   (1:N)

sync_runs    (per workflow, independent history)
sessions     (latest snapshot wins)
session_events

approved_deviations (workflow, item_key)   ← independent snapshot, no FK to current
   ├── approved_deviation_fields
   ├── approved_deviation_attributes
   ├── approved_deviation_refs
   └── approved_deviation_edits
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
| `jobs` | mutable until terminal | Terminal rows are deleted only by the current purge, with their items |
| `work_item_edits`, `work_item_events`, `item_decisions`, `job_logs`, `session_events` | audit | Never updated; deleted only when their parent item (and, for `job_logs`, its job) is purged |
| `sync_runs` | bounded ring | Newest 20 per workflow, trimmed in the insert transaction |
| `sessions` | append-only | Latest row wins; `clear()` removes all |
| `approved_deviations` | snapshot | Written on accept, refreshed on submit/closure, removed on undo/reject |
| `approved_deviation_*` | snapshot children | Replaced with the parent; cascade on delete |

## 7. Retention

Two manual purges keep the two stores independent.

### 7.1 Current work items — 24 hours

`PurgeService.purge(CURRENT)` deletes `work_items` whose latest activity
(`COALESCE(closed_at, last_seen, first_seen)`) is older than `now - 24h`, except items
with an active job (`queued`, `running`, `blocked_auth`). It deletes the item's
`work_item_fields`, `work_item_attributes`, `work_item_refs`, `work_item_edits`,
`work_item_events` and `item_decisions` in the same transaction.

It also deletes the item's `jobs` rows and their `job_logs`, but only when the job is
terminal (`succeeded`, `failed`, `cancelled`). The terminal filter is applied again in the
delete statement itself: `submit()` can enqueue a job between the item selection and the
delete, and a freshly queued job must never be removed after the API has already returned
`202`. An item whose job is still terminal-free keeps that job until the next run.

Deleting the old decisions is deliberate: a deviation that disappears and later returns
must not inherit a stale accept that would keep it out of the deck. `sessions`,
`session_events` and every `approved_*` table are out of scope.

The trade-off is explicit: the Jobs page keeps history only for items still inside the
current store. Once an item is purged, its job log is unrecoverable — `work_item_events`
records status transitions, not the Salesforce detail.

### 7.2 Approved history — 90 days

`PurgeService.purge(HISTORY)` deletes `approved_deviations` rows whose `decided_at` is
older than `now - 90d`, then deletes the four snapshot child tables. Current work items
and operational tables are untouched.

### 7.3 Properties

- Both purges are idempotent and support a dry run that returns the same counts.
- The cutoff is computed server-side; the UI never supplies or changes it.
- Both purges are operator-triggered. The one automatic deletion is the `sync_runs` ring
  (§7.4), which has no reader beyond the newest row and needs no confirmation.
- `VACUUM` is not run automatically; SQLite may keep free pages until a later manual
  maintenance step. Deleting rows does not shrink the file.

### 7.4 Sync runs — 20 rows per workflow

`SyncRunRepository.record()` inserts the new sample and, in the same transaction, deletes
every row outside the newest 20 for each workflow:

```sql
DELETE FROM sync_runs
 WHERE id NOT IN (
   SELECT id FROM (
     SELECT id, ROW_NUMBER() OVER (PARTITION BY workflow ORDER BY id DESC) AS rn
       FROM sync_runs
   ) WHERE rn <= 20
 );
```

`id DESC` is the same order `recent(limit=20)` reads, so the retained window equals the
documented read window. `latest()` is unaffected because the newest row is always kept.
The statement runs on every insert and trims every workflow at once, so rows belonging to
a workflow that is no longer registered do not linger.

No index is needed: the table never exceeds 20 rows per workflow, and both the trim and
`latest()` order by the `id` primary key. This is why the change carries no schema
migration.

## 8. Repository ownership map

| Table | Repository |
|---|---|
| `work_items` | `WorkItemRepository` |
| `work_item_fields` | `FieldValueRepository` |
| `work_item_attributes` | `AttributeRepository` |
| `work_item_refs` | `PageRefRepository` |
| `work_item_edits` | `EditRepository` |
| `work_item_events` | `EventRepository` |
| `item_decisions` | `DecisionRepository` |
| `jobs`, `job_logs` | `JobRepository` |
| `sync_runs` | `SyncRunRepository` |
| `sessions`, `session_events` | `SessionRepository` |
| `approved_deviations`, `approved_deviation_*` | `ApprovedHistoryRepository` |
| current/history purge SQL | `PurgeRepository` |

No other module contains SQL. The API layer (`app/api`) talks to these repositories
through `WorkItemService`/`AdminService` and never issues SQL itself.
