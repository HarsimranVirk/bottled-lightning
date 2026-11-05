# Decision Register — Delivery (launchers, updates, LAN access)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v3 |
| **Date** | 2026-11-05 |
| **Locked** | 2026-11-05 (v2); amended v3 2026-11-05 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | Double-click launchers, self-update install, LAN address on the home page |
| **Companions** | `docs/FR-delivery.md`, `docs/class-design-delivery.md`, `docs/data-model-delivery.md`, `docs/api-delivery.md` |

## Context

The launchers, release workflow, version compare and update **check** already exist. The
install half is a stub (`apply_pending` returns `{"status": "none"}`), the cache never
expires, the digest is never verified, there is no install UI, and a second double-click
starts a process that fails to bind the port. The home page also has no address for
reaching the app from another device.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | The double-click entry points stay shell scripts (`start.command`, `start.bat`) plus `fetch_release.py`; no packaged installer. | PyInstaller/MSI/signed app bundle. | The scripts already bootstrap a venv, install the wheel and start the app; a native installer adds signing, notarisation and OS-specific build work for no functional gain now. | `launchers/*`, `.gitattributes` | locked |
| D-02 | Before any bootstrap work, a launcher probes `http://127.0.0.1:<port>/`; if it answers, it opens the browser and exits. | Letting a second process fail to bind. | This is the exact failure seen when double-clicking twice; opening the existing app is the behaviour the operator expects. | `launchers/start.command`, `launchers/start.bat` | locked |
| D-03 | The check result is cached with `checked_at` for **6 hours** (`SF_UPDATE_CHECK_HOURS`); manual checks bypass it. | Cache forever (today) or no cache. | Forever means a release published after boot is never seen; no cache spams the GitHub API and slows every boot. | `app/updater.py`, `app/config.py` | locked |
| D-04 | Install verifies the GitHub HTTPS URL, the `sha256:` asset digest when present, and the version inside `app/__init__.py`. | Trusting the tag or the wheel filename. | The wheel is code executed as the app; both checks are cheap and the release workflow already publishes `SHA256SUMS.txt`. | `app/updater.py` | locked |
| D-05 | A source checkout refuses installs unless `SF_UPDATE_ALLOW_SOURCE=1`. | Installing into any environment. | Dev checkouts run editable code; silently replacing it with a release wheel is surprising and can hide local changes. The flag already existed. | `AdminService._update_block_reason`, `app/config.py` | locked |
| D-06 | An install is refused while a queued/running/blocked job exists, a manual login is in progress, or another install is running. | Install at any time. | Replacing the process mid-write or mid-login loses work and leaves a stale browser session; the queue and login are the only two long-running operations. | `app/api/services.py`, `app/api/routes/admin.py` | locked |
| D-07 | Restart is `os.execv(sys.executable, [sys.executable, "-m", "app.main", *args])` after the browser runtime stops. | Spawn a child then exit, or require a manual restart. | Spawning races the port (the child may bind before the old socket closes); exec replaces the process image and releases the socket. | `app/updater.py`, `AdminService._restart` | locked |
| D-08 | The install runs in a background thread; the endpoint returns `202` and status moves `installing` → `installed`/`failed`. | Synchronous install inside the request. | A pip install takes seconds and would time out the HTTP call; a failure must leave the old process running and report why. | `AdminService.install_update`, `updater.apply_pending` | locked |
| D-09 | `SF_UPDATE_POLICY=auto` (default) checks after boot and then every 10 minutes, installing only when the guard passes; an attempted version is not retried automatically. `notify` and `off` remain. | A single boot check, or an unconditional retry loop. | A boot-only check misses the moment the queue drains; retrying a broken wheel indefinitely spams pip and logs. Manual install bypasses the attempted-version guard. | `AdminService.start_auto_update` | locked |
| D-10 | The home page gets the LAN address from `GET /api/network`; `Settings` gains the actual `host`/`port` so the answer matches the bind. | Detecting the IP in the browser or hard-coding 8765. | A browser cannot see the server's interfaces, and the port can be overridden from the CLI; the server is the only reliable source. | `app/config.py`, `app/utils/network.py`, `app/api/*`, frontend | locked |
| D-11 | The home page shows the LAN URL with a copy action, the local URL, and a warning when the server binds to loopback. | Showing only the IP, or nothing when loopback. | The URL is what the operator types on the other device; the loopback warning explains why the LAN URL is missing (`SF_HOST=0.0.0.0`). | `frontend/src/components/NetworkCard.tsx`, `HomePage.tsx` | locked |
| D-12 | The update card shows the current/latest version and an **Install update** action, disabled while a job runs or an install is running. | Auto-only with no visible state. | The operator needs to see that an install is happening before the app restarts, and needs a manual path when auto is blocked. | `frontend/src/components/UpdateCard.tsx`, `HomePage.tsx` | locked |
| D-13 | This release is **0.4.0**, built locally as a wheel and uploaded by hand; the tag-driven CI workflow stays for later. | Tagging and pushing now. | The user wants a local artefact first; CI/CD is explicitly later. The workflow's tag/version guard remains intact for when it is used. | `app/__init__.py`, `dist/`, `README.md` | locked |
| D-14 | The launchers export `SF_DATA_DIR=<app home>/data` (unless already set), so installed state lives beside the venv rather than inside `site-packages`. | Leaving the default (`site-packages/data`). | The default survives pip upgrades but is erased if the venv is recreated; the top of the app-data folder is the obvious, durable place and matches the “installed runs keep state in the OS app-data dir” rule. | `launchers/start.command`, `launchers/start.bat`, `docs/guide-delivery.md` | locked |
| D-15 | On a first start the launcher waits until the app answers and then opens the browser; an already-running app is opened immediately (D-02). | Printing the URL and requiring a manual copy. | Double-click should finish the job; a background readiness probe is two small shell blocks and keeps the app in the foreground for normal Ctrl-C handling. | `launchers/start.command`, `launchers/start.bat` | locked |

## Consequences

- A submit or extraction in progress blocks an update; the auto loop tries again later.
- The app restarts itself after a successful install: the browser tab reconnects and shows
  the new version. An install failure keeps the current version running and reports it.
- The first release must be uploaded manually before the launchers can bootstrap from
  GitHub; until then they fall back to a wheel placed beside the launcher.
- `data/updates/` holds one transient wheel; deleting it is always safe.
- The LAN URL only exists when the server binds `0.0.0.0` (the default) **and** a LAN
  interface is detectable.

## Open items at lock time

- Cache TTL is fixed at 6 h with `SF_UPDATE_CHECK_HOURS` as the override; the user was
  unsure, so this is the proposed default and can be changed before lock.
