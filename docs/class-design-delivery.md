# Class Design — Delivery (launchers, updates, LAN access)

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Companions** | `docs/FR-delivery.md`, `docs/data-model-delivery.md`, `docs/api-delivery.md`, `docs/decisions-delivery.md` |

## 1. Ownership

| Concern | Owner |
|---|---|
| Release lookup, version compare, download, verify, pip install, re-exec | `app/updater.py` (module functions, as today) |
| When it is safe to install, auto loop, login flag | `app/api/services.py::AdminService` |
| Bind host/port and LAN address | `app/config.py`, `app/utils/network.py` |
| HTTP surface | `app/api/routes/admin.py` + `AdminService` |
| Double-click bootstrap | `launchers/start.command`, `launchers/start.bat` |
| Home-page presentation | `frontend/src/components/{NetworkCard,UpdateCard}.tsx`, `HomePage.tsx` |

## 2. `app/config.py`

```python
class Settings:
    ... existing fields ...
    host: str = "0.0.0.0"          # actual uvicorn bind host
    port: int = 8765               # actual uvicorn port
    update_check_ttl_hours: float = 6.0
```

`load_settings()` fills them from `SF_HOST`/`SF_PORT`; `main()` overrides them with the
parsed `--host`/`--port` using `dataclasses.replace`, so the API reports what the process
actually bound. Defaults keep every existing test constructor valid.

Module constants: `UPDATE_CHECK_TTL_HOURS`, `UPDATE_INSTALL_DIR = DATA_DIR / "updates"`.

## 3. `app/utils/network.py`

```python
def lan_ip() -> str | None:
    """Best-effort outbound interface address; None when unavailable."""
```

Moves `_lan_ip` out of `main.py` so both the boot banner and the API use one helper. It
opens a UDP socket to `8.8.8.8:80` (no packets sent), reads `getsockname()[0]`, and returns
`None` on `OSError`. No caching: the address can change (Wi-Fi/VPN).

## 4. `app/updater.py`

Existing functions stay. Changes:

- `_finish(result)` injects `checked_at` (UTC ISO) before saving and copying to the state.
- `_fresh(cached)` becomes a real TTL check against `update_check_ttl_hours`.
- `check_for_update()` carries `sha256` from the asset `digest` (`sha256:…`).
- New:

```python
def apply_pending(
    guard: Callable[[], str | None] | None = None,
    restart: Callable[[], None] | None = None,
) -> dict[str, JsonValue]:
    """Download, verify and install the pending wheel; never raises."""
```

Flow: guard → `check_for_update(force=True)` → require `update_available` →
`_download_wheel(url, dest)` → `_verify_digest(path, sha256)` → `verify_wheel(path, latest)`
→ `_install_wheel(path)` (`sys.executable -m pip install --upgrade`) → set status
`installed` → `restart or _restart()`.

- `_restart()` = `os.execv(sys.executable, [sys.executable, "-m", "app.main", *sys.argv[1:]])`.
- `_set_status("installing"/"installed"/"failed")` keeps `/api/updates` truthful.
- The downloaded wheel is deleted in a `finally`.
- `start_auto_update()` is removed: scheduling belongs to `AdminService`, which knows the
  queue and login state.

## 5. `AdminService`

```python
class AdminService:
    def __init__(...):  # existing args
        self._install_lock = threading.Lock()
        self._login_running = threading.Event()
        self._auto_attempted: str | None = None
        self._auto_started = False

    def network(self) -> NetworkView: ...
    def update_status(self) -> UpdateStatusView: ...
    def install_update(self, *, auto: bool = False) -> UpdateStatusView: ...
    def start_auto_update(self) -> None: ...
```

- `network()` builds the view from `settings.host/port`, `lan_ip()` and
  `settings.host not in {"127.0.0.1", "localhost", "::1"}`.
- `_update_block_reason()` returns `None` or one of: `"jobs are running"`, `"manual login
  in progress"`, `"source checkout (SF_UPDATE_ALLOW_SOURCE=1 to allow)"`, `"install already
  running"`.
- `install_update(auto=False)`:
  - auto: skip when the latest version was already attempted in this process;
  - manual: raise `ApiError(409, reason, "update_blocked")` when blocked;
  - acquire the install lock, set `installing`, spawn a daemon thread running
    `updater.apply_pending(guard=self._update_block_reason,
    restart=self._restart)`, return the current status (route sends `202`).
- `_restart()` stops the browser runtime (`self._runtime.stop()`) and then calls
  `updater.apply_pending`'s restart callback; the worker thread owns the exec.
- `start_auto_update()` starts a daemon loop when `UPDATE_POLICY == "auto"` and
  `UPDATE_AUTO_START`: sleep 20 s (let uvicorn bind), then every 10 minutes call
  `install_update(auto=True)`; any exception is logged, never raised.
- `login()` wraps its spawned `_login` coroutine with `self._login_running.set()` /
  `clear()` so an install cannot replace the process mid-login.

`AdminPort` gains `network()` and `install_update()`.

## 6. Routes

- `GET /api/network` → `NetworkView`.
- `POST /api/updates/installations` → `202` `UpdateStatusView`; `409` with
  `code="update_blocked"` and the reason.
- `GET /api/updates` and `POST /api/updates/checks` stay.

## 7. Launchers

`start.command` / `start.bat` gain a probe before the venv work:

```
if the app answers on http://127.0.0.1:$PORT/ then open the browser and exit 0
```

macOS uses `curl -fsS`; Windows uses PowerShell `Invoke-WebRequest` with a 2 s timeout.
`PORT` comes from `SF_PORT` (default 8765).

## 8. Frontend

- `useNetwork()` → `GET /api/network`.
- `useInstallUpdate()` → `POST /api/updates/installations`, then poll `/api/updates`.
- `NetworkCard`: LAN URL + copy button, local URL, loopback warning.
- `UpdateCard`: current version, `Update vX available` + **Install update**, disabled while
  `queue.inFlight > 0` or installing; shows the installer status/error.
- Both live on `HomePage`; no new route.

## 9. Tests

- Updater: TTL freshness, digest carried, `apply_pending` guard, digest mismatch, install
  failure leaves status `failed` (pip and download mocked).
- `AdminService`: blocked when jobs exist, blocked mid-login, blocked in a source checkout,
  auto skips an attempted version.
- API: `/api/network` shape; install `409` code; install `202`.
- Frontend: `NetworkCard` copy + loopback warning; `UpdateCard` disabled/installing states.
- Launchers: shell syntax check (`bash -n`) and a manual double-click run.
