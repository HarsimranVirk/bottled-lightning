# Functional Requirements — Delivery (launchers, updates, LAN access)

| | |
|---|---|
| **Status** | Implemented — amended 2026-11-07 (update-check resilience) |
| **Version** | v1.2 |
| **Date** | 2026-11-07 |
| **Scope** | Double-click launchers, self-update, the home-page LAN address, release artefacts, failure recovery of the update check |

---

## 1. Purpose

Make the app something an operator can run without a terminal, keep current without
re-downloading it, and reach from another device on the same network.

## 2. Launchers

- **FR-1.1** macOS (`start.command`) and Windows (`start.bat`) launchers start the app on
  a double-click and keep the window open on failure.
- **FR-1.2** A launcher creates a private virtualenv under the OS app-data directory
  (`~/Library/Application Support/bottled-lightning` / `%LOCALAPPDATA%\bottled-lightning`),
  installs the newest GitHub release wheel (or a wheel placed beside the launcher),
  installs Chromium, and starts the webapp.
- **FR-1.3** If the app is already answering on `127.0.0.1:PORT`, the launcher opens the
  browser at that address and exits instead of starting a second server.
- **FR-1.4** Every failure prints a readable cause and waits for a key press before the
  window closes.
- **FR-1.5** Overrides remain: `BL_HOME`, `BL_WHEEL`, `BL_REINSTALL=1`, `SF_UPDATE_REPO`,
  `SF_DATA_DIR`, `SF_HOST`, `SF_PORT`.
- **FR-1.6** On a first start the launcher opens the browser as soon as the app answers on
  the port; the app stays in the foreground so Ctrl-C and closing the window stop it.
- **FR-1.7** Installed state (database, session snapshot, update state) lives at
  `<app home>/data`; the launcher exports `SF_DATA_DIR` unless the user already set it, so
  recreating the virtualenv does not erase the operator's data.

## 3. Update check

- **FR-2.1** The updater asks GitHub for the latest release and compares its tag with the
  running `app/__init__.py` version.
- **FR-2.2** A **successful** result (`update-available`, `up-to-date`, `disabled`) is
  cached in `update_state.json` with `checked_at`; it is reused for **6 hours**
  (`SF_UPDATE_CHECK_HOURS`), or bypassed by a forced/manual check. A `failed` result is
  never written to the cache: it is published for the UI only, so the next check really
  hits the network.
- **FR-2.5** A cached `failed` row written by an older version is ignored (treated as
  "no cache") and is overwritten by the next successful check; it is never replayed.
- **FR-2.6** A failed check carries an operator-readable sentence in `error` and the raw
  exception text in `detail`; both stay within the existing payload shape.
- **FR-2.3** A check never raises. Missing repo/release, offline and malformed payloads
  are reported as `up-to-date` (404) or `failed` with a message.
- **FR-2.4** The release asset's `digest` (`sha256:…`) is carried into the result when
  GitHub provides it.

## 4. Install

- **FR-3.1** Only `https://github.com/…` download URLs are accepted.
- **FR-3.2** The wheel is verified before installation: SHA-256 matches the release digest
  when present, and `app/__init__.py` inside the wheel declares the release version.
- **FR-3.3** Installation uses the running interpreter's pip; success restarts the process
  with `os.execv(sys.executable, [sys.executable, "-m", "app.main", *args])`.
- **FR-3.4** An install is refused with `409` when: a queued/running/blocked job exists, a
  manual login is in progress, another install is running, or the app runs from a source
  checkout without `SF_UPDATE_ALLOW_SOURCE=1`.
- **FR-3.5** The install runs off-request: the endpoint returns `202`, status becomes
  `installing`, then `installed` (immediately before the restart) or `failed`. A failure
  leaves the current process running and reports the error.
- **FR-3.6** Downloaded wheels live under `data/updates/` and are deleted after a
  successful install (and on failure, best effort).

## 5. Automatic and manual updates

- **FR-4.1** `SF_UPDATE_POLICY=auto` (default): after boot, once the queue is idle and no
  login is running, an available update is installed and the app restarts. If the guard
  blocks it, the check result remains available for a manual install.
- **FR-4.2** `SF_UPDATE_POLICY=notify`: check only; the operator installs explicitly.
- **FR-4.3** `SF_UPDATE_POLICY=off`: no checks and no installs.
- **FR-4.4** The home page shows the update status and an **Install update** action when a
  version is available. The action is disabled while a job runs or an install is running.
- **FR-4.5** When the last check failed, the update card shows a **Check again** action
  that forces a check (`POST /api/updates/checks`), reports it while it runs, and replaces
  the displayed status with the response. The action is not shown in any other state and
  does not depend on the job queue (a check never installs anything).

## 6. LAN access on the home page

- **FR-5.1** `GET /api/network` returns the bind host, port, LAN IP, LAN URL, local URL and
  whether LAN access is enabled.
- **FR-5.2** The home page shows the LAN URL (for another device) and the local URL, with
  a copy action for the LAN URL.
- **FR-5.3** When the server binds to loopback, the page says LAN access is off and how to
  enable it (`SF_HOST=0.0.0.0`).
- **FR-5.4** LAN IP detection is best-effort; when unavailable the page says so and never
  fails.

## 7. Release artefacts

- **FR-6.1** The wheel is built with `python -m build --wheel` after
  `npm --prefix frontend run build`; it must contain `app/web/index.html`.
- **FR-6.2** The version lives in `app/__init__.py`; this release is **0.4.0**.
- **FR-6.3** Until CI is enabled, the wheel is built locally and uploaded to a GitHub
  release by hand, together with `SHA256SUMS.txt` and the launcher zip.
- **FR-6.4** The existing `.github/workflows/release.yml` remains the future CI path and
  must keep the tag/version guard.

## 8. Out of scope

- Code signing, notarisation and MSI installers.
- Background updates while a job is running.
- TLS or reverse-proxy configuration.

## 9. Edge cases and acceptance criteria — update-check resilience

**Edge cases**

| Case | Expected behaviour |
|---|---|
| Boot check fails because Wi-Fi/VPN/captive portal is not ready | The card shows the failure immediately; the auto loop retries after 10 minutes and the operator can force a retry at once. Nothing is cached, so a recovered network is visible on the next attempt. |
| The first check after upgrade runs against a `failed` row in `update_state.json` | The row is ignored (no cache hit); the check goes to GitHub. |
| A failed check never reached GitHub | `error` says the network/certificate failed in plain language; `detail` keeps `URLError`/OpenSSL text for support. |
| Certificate genuinely untrusted (stale root store, inspecting proxy) | Still `failed`; the message points at network/VPN/proxy and the operator can retry. Verification is **not** skipped. |
| Check again pressed repeatedly | Each press forces one check; the button is disabled while the request is in flight. |
| Check again pressed while jobs run | Allowed; a check performs no install. |
| Check again pressed while an install runs | The card is in the `installing` state, so the button is not rendered. |
| `POST /api/updates/checks` fails at the network level | `200` with `status: "failed"` (never a 5xx); the card renders the new `error`. |

**Acceptance criteria**

- **AC-1** A check failure leaves `update_state.json` unchanged (or absent); a following
  non-forced check invokes `_fetch_json` again.
- **AC-2** A `failed` row already in `update_state.json` does not short-circuit a check.
- **AC-3** A certificate error yields an `error` string containing "certificate", while
  `detail` contains the original OpenSSL/`URLError` text.
- **AC-4** With `status: "failed"`, `UpdateCard` renders **Check again**; clicking it calls
  the check mutation once and the button is disabled while pending.
- **AC-5** No other card state renders **Check again**.
- **AC-6** `GET /api/updates` still returns the same six fields; TypeScript types are
  unchanged.
