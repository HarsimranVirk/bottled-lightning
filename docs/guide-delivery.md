# Guide — Delivery (launchers, updates, LAN access)

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Feature** | Double-click start, self-update, LAN address on the home page |
| **Design** | `docs/decisions-delivery.md` (v2, LOCKED), `docs/FR-delivery.md`, `docs/class-design-delivery.md`, `docs/api-delivery.md` |

## What it does

1. **Double-click start.** `start.command` (macOS) and `start.bat` (Windows) create a
   private virtualenv under the OS app-data directory, install the newest release wheel
   (or a wheel beside the launcher), install Chromium and start the app. A second
   double-click detects the running app and simply opens it in the browser.
2. **Self-update.** The app checks GitHub releases (cached 6 h). With the default
   `auto` policy it waits until no job or login is running, downloads the new wheel,
   verifies it, installs it and restarts itself. The home page also offers an
   **Install update** button.
3. **LAN access.** The home page shows the address to open on another device
   (`http://<lan-ip>:8765`) with a copy button, plus the local address.

## How to use it

### Start

Run the launcher from a terminal. Finder double-click can be blocked by Gatekeeper, and
SmartScreen can block a Windows double-click, but a terminal launch is not blocked.

**macOS**

```bash
cd ~/bottled-lightning-launchers
./start.command
```

If it says **“permission denied”**, run `chmod +x start.command` once. If macOS still
blocks it, `xattr -dr com.apple.quarantine .` is the fallback.

**Windows** (PowerShell)

```powershell
cd $HOME\Downloads\bottled-lightning-launchers
.\start.bat
```

If SmartScreen appears: **More info → Run anyway**. `Unblock-File .\start.bat` is the
fallback if Windows refuses to run it.

On first start the launcher waits until the app answers and then opens the browser
automatically (`http://127.0.0.1:8765`, honouring `SF_PORT`). The terminal stays in the
foreground; closing it stops the app. If the app is already running, the launcher just
opens the browser instead of starting a second server.

### First launch warnings (unsigned build)

The launchers are not code-signed, so Finder/Explorer may warn. Running from a terminal is
the normal path and avoids both prompts.

**macOS — “Apple could not verify … is free of malware”**

1. Use the Terminal command above (`./start.command`).
2. If it says “permission denied”: `chmod +x start.command`.
3. If macOS still blocks it: `xattr -dr com.apple.quarantine .` in the folder.
4. If Terminal says “Operation not permitted” while in `~/Downloads`, move the folder to
   your home folder or grant Terminal access under **Privacy & Security → Files and
   Folders**.

**Windows — “Windows protected your PC” / “publisher could not be verified”**

1. Run `.\start.bat` from PowerShell, or double-click and choose **More info → Run
   anyway**.
2. If Windows refuses: `Unblock-File .\start.bat` (or right-click the file → **Properties**
   → tick **Unblock**).
3. If antivirus quarantines the launcher, restore it and add a folder exclusion.

Verify the wheel against `SHA256SUMS.txt` (`shasum -a 256` on macOS,
`certutil -hashfile <file> SHA256` on Windows). The warnings disappear when the launcher
is signed (Developer ID + notarisation on macOS, Authenticode on Windows), which is
planned for public distribution.

### Update

- Automatic: leave the app running. When a newer release exists and the queue is idle, it
  installs and restarts; the open tab reconnects.
- Manual: Home → **Install update**. The button is disabled while jobs are queued or
  running. While installing, the card shows “Installing … the app will restart”.
- Check now: `POST /api/updates/checks`.
- Current status: `GET /api/updates`.

```bash
curl -s -X POST http://127.0.0.1:8765/api/updates/checks
curl -s -X POST http://127.0.0.1:8765/api/updates/installations
```

### Open on another device

Home → **Open on another device** → copy the LAN link. Both devices must be on the same
network. If the card says LAN access is off, start with `SF_HOST=0.0.0.0` (the default)
instead of `127.0.0.1`.

## Configuration and state

| Setting | Default | Meaning |
|---|---|---|
| `SF_HOST` / `SF_PORT` | `0.0.0.0` / `8765` | Bind address; `0.0.0.0` enables LAN access |
| `SF_UPDATE_POLICY` | `auto` | `auto`, `notify` (check only) or `off` |
| `SF_UPDATE_CHECK_HOURS` | `6` | Cache TTL for the GitHub check |
| `SF_UPDATE_ALLOW_SOURCE` | `0` | Allow installs from a source checkout |
| `SF_DATA_DIR` | `<app home>/data` | Database, session snapshot and update state |
| `BL_HOME` | OS app-data | Launcher virtualenv root |
| `BL_WHEEL` | — | Install a specific wheel on first run |
| `BL_REINSTALL` | `0` | Force a reinstall on the next launch |
| `SF_UPDATE_REPO` | `harsimranvirk/bottled-lightning` | Release source |

State:

- `<app home>/data` — database, session snapshot and update state. The launcher sets
  `SF_DATA_DIR` to this path unless you already set it, so recreating the virtualenv does
  not erase your data.
- `<data_dir>/update_state.json` — last check/install result (safe to delete).
- `<data_dir>/updates/` — transient wheel during an install (safe to delete).
- The launcher keeps its virtualenv; the app never reads it.

## Release / upload checklist

```bash
npm --prefix frontend run build
python -m build --wheel
cd dist && shasum -a 256 bottled_lightning-*.whl > SHA256SUMS.txt
cd ../launchers && zip -r ../dist/bottled-lightning-launchers.zip \
  start.command start.bat fetch_release.py
```

Upload these three files to the GitHub release:

| File | Purpose |
|---|---|
| `bottled_lightning-<version>-py3-none-any.whl` | the app |
| `SHA256SUMS.txt` | digest the updater checks |
| `bottled-lightning-launchers.zip` | the double-click start scripts |

The version in `app/__init__.py` must equal the tag without `v` (`0.4.0` → `v0.4.0`). The
existing CI workflow performs the same steps on a tag when you enable it.

## Five most likely failure modes

1. **“Wait for the running jobs to finish” / install returns `409`.** A job or a manual
   login is active. Finish or cancel it, then press Install again (or let auto retry).
2. **Install returns `409` “source checkout”.** You are running from the git checkout. Use
   a release install, or set `SF_UPDATE_ALLOW_SOURCE=1` deliberately.
3. **Install failed.** The card shows the reason (pip output or digest mismatch) and the
   app keeps running. Download the wheel manually and install it with pip.
4. **LAN card says LAN access is off.** The server is bound to loopback. Start with
   `SF_HOST=0.0.0.0` and reload; check the computer firewall if the link still fails.
5. **The launcher says no wheel was found.** No GitHub release exists yet, or the lookup
   failed offline. Download the wheel from the release page, put it beside the launcher,
   double-click again.

## Where to read more

- Decisions: `docs/decisions-delivery.md` (D-01…D-13, locked 2026-11-05).
- Requirements: `docs/FR-delivery.md`.
- Internals: `docs/class-design-delivery.md`, `docs/api-delivery.md`.
- State: `docs/data-model-delivery.md`.
- Execution order: `docs/refactor-plan-delivery.md`.
