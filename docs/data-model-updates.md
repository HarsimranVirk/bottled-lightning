# Data Model — Update-check resilience

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Companions** | `docs/FR-delivery.md` (v1.2) FR-2.2/2.5/2.6, `docs/class-design-updates.md`, `docs/api-updates.md`, `docs/decisions-updates.md` |

## 1. SQLite

**No change.** No table, column, index, migration or retention rule. The schema stays v5
and `data/app.db` is not read or written by this change.

## 2. `update_state.json`

`<data_dir>/update_state.json` — check-state cache, not domain data. Owner:
`app/updater.py` (`_save_cache`/`_load_cache`). Rewritten in place; deleting it is always
safe.

| Field | Type | Meaning | Persisted now |
|---|---|---|---|
| `status` | string | `update-available`, `up-to-date`, `disabled` are cached; `failed` is never written | success only |
| `update_available` | bool | Latest tag is newer than the running version | success only |
| `latest` | string? | Release tag (`v0.5.0`) | success only |
| `download_url` | string? | GitHub HTTPS wheel URL | success only |
| `sha256` | string? | Lower-case hex digest from the asset `digest` | success only |
| `checked_at` | string? | UTC ISO timestamp; drives the 6 h TTL | success only |
| `error` | string? | Operator-readable failure sentence | never |
| `detail` | string? | Raw exception text (support only) | never |

`installing` / `installed` / `blocked` are in-memory `_state` values published by
`_set_status`; they were never written to this file and still are not.

## 3. Migration and existing rows

- A file may already contain `{"status": "failed", …}` written by v0.5.x or earlier.
  **No migration, no rewrite, no delete:** `_cached_check()` treats any `failed` row as a
  cache miss, so the next check goes to GitHub and the file is overwritten by its
  result. This is the whole migration path.
- A successful cached row keeps working unchanged, including its `checked_at` TTL.
- Nothing else reads the file, so no reader needs a version check.

## 4. Retention

Unchanged: one row, overwritten in place, no purge job. The file remains disposable; the
only new property is that it can no longer be stale-`failed`.

## 5. In-process state

`updater._state` (guarded by `_state_lock`) keeps the same six operator-visible fields and
is what `GET /api/updates` returns. A process restart resets it to
`{"status": "idle", "detail": "", "result": None}`; the auto loop publishes the first real
result ~20 s later. No new in-memory store, no queue, no thread-local state.

## 6. Browser state

**No change.** The card reads the API through the existing `['updates']` query key; the
retry action patches that cache with the POST response. Nothing is added to
`localStorage`.
