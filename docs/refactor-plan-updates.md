# Refactor Plan — Update-check resilience

| | |
|---|---|
| **Status** | Ready — executing |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Depends on** | `docs/decisions-updates.md` (v1, LOCKED 2026-11-07) |
| **Touches** | `app/updater.py`, `tests/test_updater.py`, `frontend/src/components/UpdateCard.tsx`, `frontend/src/components/UpdateCard.test.tsx`, `frontend/src/queries.ts`, `frontend/src/pages/HomePage.tsx`, `app/__init__.py`, `docs/*` |
| **Does not touch** | the SQLite schema, workflow pipelines, extraction, submission, install guards, the TLS default context |

## 1. Slices

### Slice 1 — cache and failure semantics (D-01, D-02, D-03, D-05; FR-2.2/2.5/2.6)

- Split `_finish` into `_publish` + `_finish(..., persist=True)`.
- Add `_cached_check()` that treats a `failed` row as a miss; use it in `check_for_update`.
- Add `_reason(error)` and `_failed(reason, detail)`; route every failure path through
  `_finish(result, persist=False)`.
- `apply_pending`'s catch-all reports `_reason(exc)` in `error`, raw text in `detail`.
- Tests: failure not persisted (file absent/unchanged), second non-forced call refetches,
  legacy `failed` row ignored, certificate/timeout/DNS wording, HTTP status wording,
  failed payload nulls `latest`/`download_url`.

### Slice 2 — retry action (D-04; FR-4.5)

- `useCheckUpdate()` in `queries.ts` (POST `/api/updates/checks`, patch `['updates']`).
- `UpdateCard` gains `checking`/`onCheck`; renders **Check again** only when
  `status === 'failed'`, disabled while pending.
- `HomePage` wires the hook.
- Component test: button present only on failure, calls `onCheck` once, disabled while
  checking.

### Slice 3 — docs and release (D-06; FR header)

- Guide `docs/guide-updates.md`, ledger row, version bump to **0.5.1**.
- Gate commands below; PR, merge, tag `v0.5.1`, CI publishes the wheel + launchers.

## 2. Cutover

No migration and no feature flag: deploying the new code stops writing failures to the
cache and adds the button. An existing `failed` row is ignored on the first check. The
frontend and backend can be deployed in either order (the payload is unchanged; an old
frontend simply ignores the new button).

## 3. Rollback

Revert the commit. `update_state.json` stays valid in both directions (`failed` rows are
simply ignored by the new code and were written by the old one). No data is deleted.

## 4. Gate commands

```bash
ruff check app/ frontend/
mypy --strict app tests
python -m unittest discover -s tests
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

`python -m build --wheel` only if the wheel is built locally (CI builds it on the tag).
