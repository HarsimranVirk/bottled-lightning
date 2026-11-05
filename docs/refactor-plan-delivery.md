# Refactor Plan — Delivery (launchers, updates, LAN access)

| | |
|---|---|
| **Status** | Ready — executing |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Depends on** | `docs/decisions-delivery.md` (v2, LOCKED 2026-11-05) |
| **Touches** | `app/config.py`, `app/utils/network.py`, `app/updater.py`, `app/api/*`, `app/main.py`, `frontend/src/**`, `launchers/*`, `app/__init__.py`, `tests/**`, `docs/guide-delivery.md` |
| **Does not touch** | the database schema, workflow pipelines, extraction, purge |

## 1. Slices

### Slice 1 — address and network view (D-10, D-11, FR-5)

- `Settings.host`/`Settings.port` (defaults) and `load_settings`; `main()` replaces them
  with the parsed `--host`/`--port` so the view matches the bind.
- Move `_lan_ip` to `app/utils/network.py` as `lan_ip() -> str | None`.
- `NetworkView` + `AdminService.network()` + `GET /api/network`.
- Tests: endpoint shape, loopback disable, undetectable IP.

### Slice 2 — install pipeline and guards (D-03…D-09, FR-2…FR-4)

- `updater`: `checked_at` + 6 h TTL, digest carried into the result, `apply_pending`
  (download → sha256 → wheel version → pip → status → restart), cleanup.
- `AdminService`: install lock, login flag, guard reasons, `install_update`, auto loop
  (20 s initial delay, 10 min cadence, attempted-version guard).
- Routes: install returns `202`/`409`.
- Tests: stale cache refetches, digest mismatch, guard matrix, install failure, auto skip.

### Slice 3 — home page (D-11, D-12, FR-4.4, FR-5.2–5.4)

- Regenerate `types.ts`.
- `useNetwork`, `useUpdates`, `useInstallUpdate`.
- `NetworkCard` (LAN URL + copy, local URL, loopback warning) and `UpdateCard` (version,
  install button, disabled/installing/failed states).
- Home page uses both. Component tests.

### Slice 4 — launchers (D-02)

- Probe `127.0.0.1:$PORT` before bootstrapping; open the browser and exit when it answers.
- `bash -n launchers/start.command`; confirm `start.bat` is still CRLF.

### Slice 5 — release artefacts (D-13)

- Bump `app/__init__.py` to `0.4.0`.
- `npm --prefix frontend run build` → `python -m build --wheel`.
- Verify `app/web/index.html` is in the wheel; write `dist/SHA256SUMS.txt` and
  `dist/bottled-lightning-launchers.zip`.

### Slice 6 — Phase C

`docs/guide-delivery.md`, ledger `review`, walkthrough, live double-click/update test where
possible.

### Slice 7 — launcher polish (D-14, D-15)

- Export `SF_DATA_DIR=<app home>/data` in both launchers (unless already set).
- Open the browser when the app answers on a first start (background readiness poll; the
  app stays in the foreground).
- Rebuild `dist/bottled-lightning-launchers.zip`.

## 2. Gates

```bash
source .venv/bin/activate
python -m unittest discover -s tests
mypy --strict app tests tools
uvx ruff check app/ tools/ tests/
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run
npm --prefix frontend run build
python -m build --wheel
```

## 3. Cutover

- Restart the backend. Until a release exists, auto-update reports `up-to-date` (404).
- Upload the wheel manually; afterwards the launchers bootstrap from GitHub.

## 4. Rollback

- Revert the commit and restart. The installed wheel remains until replaced.
- `update_state.json` and `data/updates/` can be deleted safely.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Update replaces the app mid-job | Guard checks queued/running/blocked jobs and login |
| Bad wheel installed | GitHub URL + digest + embedded version checks |
| Endless auto retry | Attempted-version guard; manual install bypasses it |
| LAN URL wrong after network change | 10 s poll; best-effort detection |
| Launcher opens a stale tab | Probe before venv work; opens the current app |
