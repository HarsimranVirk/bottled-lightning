# bottled-lightning

Salesforce UI Automation Webapp — captures data out of Lightning and pours it
into SQLite.

Extract data from Salesforce Lightning list views without admin access to the
org's REST API. A Python (FastAPI) backend drives a headless Playwright browser
through the Salesforce UI the same way a user would, and stores results.

## Why this architecture

- The org locks Lightning sessions to the Lightning domain and denies the REST
  API for browser sessions, so server-side API authentication is not possible
  per user. UI automation is the only working path without an admin-granted
  Connected App.
- Extraction avoids the virtualized Lightning data table by using the
  **Printable View** (renders every row in one page), with scroll-scanning as
  fallback.

## Install

Releases ship a wheel plus a small launcher bundle:

1. Download `bottled-lightning-launchers.zip` from the latest GitHub release
   (optionally also the `.whl` into the same folder for an offline install).
2. Unzip, then start it from a terminal — Finder double-click can be blocked by
   Gatekeeper/SmartScreen, but a terminal launch is not:
   - **macOS**
     ```bash
     cd ~/bottled-lightning-launchers
     ./start.command
     ```
     If it says “permission denied”, run `chmod +x start.command` once. If macOS
     specifically blocks the file, `xattr -dr com.apple.quarantine .` is the fallback.
   - **Windows** (PowerShell)
     ```powershell
     cd $HOME\Downloads\bottled-lightning-launchers
     .\start.bat
     ```
     If SmartScreen appears: **More info → Run anyway**. `Unblock-File .\start.bat` is the
     fallback if Windows refuses to run it.
3. The launcher creates a private virtualenv, installs the app (from the
   neighbouring wheel, or the newest release if none is present), fetches the
   Chromium build Playwright needs, starts the webapp and opens the browser
   (the console prints the LAN URL too).

Requires Python 3.14+ on `PATH` (macOS: `brew install python@3.14`; Windows:
python.org installer with "Add python.exe to PATH").

Runtime state lives outside the app, so updating never touches it:

    macOS:   ~/Library/Application Support/bottled-lightning/data
    Windows: %LOCALAPPDATA%\bottled-lightning\data
    Linux:   ~/.local/share/bottled-lightning/data

(A source checkout keeps using `./data`.)

## Updates

The app updates itself from GitHub releases: shortly after startup it asks the
Releases API for the newest version, downloads its wheel, verifies the version
and sha256, installs it into its own virtualenv and restarts (keeping the same
terminal window). Nothing is applied while an extraction job or a manual login
is running; the next launch retries.

    SF_AUTO_UPDATE=auto|check|off   # default auto; check = report only
    SF_UPDATE_REPO=owner/repo       # default harsimranvirk/bottled-lightning
    SF_UPDATE_DELAY=8               # seconds after boot before checking
    SF_UPDATE_INTERVAL=21600        # cache TTL for successful checks
    SF_UPDATE_TIMEOUT=10            # GitHub API timeout
    SF_GITHUB_TOKEN=...             # optional: raises the 60 req/h API limit

`GET /api/updates` reports the state, `POST /api/updates/checks` forces a check
and `POST /api/update/apply` installs + restarts. A missing repo or release is
reported as "up to date", so a not-yet-created GitHub repo is harmless. Source
checkouts never self-install (`SF_UPDATE_ALLOW_SOURCE=1` overrides).

## Development setup (Python 3.14+)

    python3.14 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    pip install -r requirements-dev.txt  # type checker for dev
    playwright install chromium    # first time only (also re-run after a
                                   # playwright upgrade — browser builds are pinned)

One-time login (opens a browser window; saves the session snapshot to the
`sessions` table in `data/app.db`):

    python -m app.salesforce.login

Run the webapp (reachable on the local network):

    python -m app.main                      # binds 0.0.0.0:8765 and prints the LAN URL
    # or: uvicorn app.main:app --host 0.0.0.0 --port 8765
    # frontend: see frontend/ (Vite + TypeScript) — `npm run dev` proxies /api to :8765
    mypy --strict app tests                  # Python typecheck
    npm --prefix frontend run typecheck      # TypeScript typecheck (strict)

## Dev tools

A read-only SQLite explorer is available by default at `/dev/db`, hidden from the main
navigation and linked from `/dev/states`:

    python -m app.main
    # open http://localhost:8765/dev/db
    # or use the link at http://localhost:8765/dev/states

Set `SF_DEV_TOOLS=0` to disable it. It is localhost-only by default;
`SF_DEV_TOOLS_ALLOW_REMOTE=1` is the explicit opt-in for LAN access. The token-bearing
`sessions` table is hidden and blocked by the read-only authorizer. CSV and real Excel
(`.xlsx`) exports are supported for the current query. The same page has two manual
retention actions: **Purge current data** keeps 24 hours of work items, and **Purge
historical data** keeps 90 days of approved-deviation snapshots. See `docs/dev-tools.md`
for the safety rules.

## Layout

    app/main.py        FastAPI app + `main()` entry point, serves the SPA
    app/config.py      settings (org URL, data dir, workers, update policy)
    app/db/            SQLite connection + schema/migrations
    app/core/          domain models, statuses, workflow seam, repositories
    app/salesforce/    async browser runtime, session snapshot, tabs, login CLI,
                       list page, object adapters
    app/jobs/          persisted queue: dispatcher, worker, auth gate, logger
    app/pipeline/      list watcher, reconciler, closure resolver
    app/api/           FastAPI routes, schemas, services
    app/workflows/     workflow implementations (deviations_z02 today)
    app/devtools/      dev-only read-only DB explorer service
    app/utils/         shared async DOM helpers and JsonValue
    app/updater.py     GitHub-release self-update (check, verify, install, restart)
    launchers/         start.command (macOS), start.bat (Windows), release lookup
    tests/             backend unit tests (`python -m unittest discover -s tests`)
    frontend/          React (Vite) + Salt DS SPA (TypeScript, strict); /api
                       proxied to the backend
    pyproject.toml     wheel packaging (frontend/dist is bundled as app/web)

## API

    GET    /api/deviations                       item list (?status, ?decision, ?query, …)
    GET    /api/deviations/{key}                 item detail: fields, attributes, refs
    PATCH  /api/deviations/{key}/field-values    propose field edits
    DELETE /api/deviations/{key}/field-values    discard proposals
    POST   /api/deviations/{key}/decisions       accept/reject a review decision
    DELETE /api/deviations/{key}/decisions       undo the latest decision
    POST   /api/deviations/{key}/jobs            enqueue one SUBMIT job (202)
    GET    /api/jobs                             filtered, sorted job page
    GET    /api/jobs/{id}                        one job with logs
    GET    /api/jobs/{id}/logs                   job logs
    DELETE /api/jobs/{id}                        cancel a queued/running job
    GET    /api/sessions                         session snapshot status + login state
    POST   /api/sessions                         open headful manual login; 202
    DELETE /api/sessions                         clear the saved snapshot
    GET    /api/syncs?workflow=…                 latest watcher refresh
    POST   /api/syncs?workflow=…                 request an immediate refresh; 202
    GET    /api/workers                          queue/concurrency state
    PATCH  /api/workers                          change concurrency
    GET    /api/version                          running version
    GET    /api/updates                          version + latest release + check state
    POST   /api/updates/checks                   force a GitHub check now
    POST   /api/updates/installations            install newest wheel and restart; 202

## Releasing

Bump `__version__` in `app/__init__.py`, commit, then push a matching tag:

    python -m unittest discover -s tests
    (cd frontend && npm ci && npm run build)
    python -m build --wheel                 # dist/bottled_lightning-<v>-py3-none-any.whl
    git tag v0.3.1 && git push origin v0.3.1

The `release` workflow builds the frontend + wheel, refuses a tag/version
mismatch, and publishes the wheel, `SHA256SUMS.txt` and
`bottled-lightning-launchers.zip` on the GitHub release. That release is what
the launcher installs and what `/api/update` upgrades to.

## Session lifecycle

Salesforce `sid` cookies are session-only, so a storage-state snapshot is taken
right after each manual login, stored in the `sessions` table, and injected on
every headless run. When the server-side session expires (org inactivity
timeout), jobs park in `blocked_auth` and resume after the next manual login.

## Roadmap

- Scheduled jobs (launchd/cron hitting /api/deviations/{key}/jobs)
- Snapshot history + diff reports (what changed since last run)
- Additional columns (opportunity, branch, approval date)
- Admin-track migration: replace UI automation with OAuth JWT calls once a
  Connected App is granted
