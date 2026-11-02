# Salesforce UI Automation Webapp

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

## Setup (Python 3.9+)

    python3 -m pip install --user -r requirements.txt
    python3 -m playwright install chromium

One-time login (opens a browser window; saves session to `sf_profile/` +
`auth.json`):

    python3 -m app.browser --login

Run the webapp:

    python3 -m uvicorn app.main:app --port 8765
    # open http://127.0.0.1:8765

## Layout

    app/main.py        FastAPI app serving API + static UI
    app/config.py      settings (org base URL, view admin URL, data dir)
    app/browser.py     Playwright session manager + login CLI
    app/extractors.py  extraction strategies (printable view, scroll scan)
    app/store.py       SQLite persistence (views, jobs, rows)
    app/routes.py      REST endpoints
    web/index.html     no-build static frontend

## API

    GET    /api/views                     tracked list views
    POST   /api/views                     add a tracked view {name, url}
    POST   /api/views/{id}/run            start an extraction job
    GET    /api/jobs                      all jobs
    GET    /api/jobs/{id}                 one job (+ row counts)
    GET    /api/views/{id}/results        latest extracted rows for a view
    GET    /api/views/{id}/results.csv    CSV download
    GET    /api/session                   login session status

## Session lifecycle

Salesforce `sid` cookies are session-only, so `auth.json` snapshots are taken
right after each manual login and injected on every headless run. When the
server-side session expires (org inactivity timeout), jobs fail with a clear
"session expired" state and the UI prompts for `--login`.

## Roadmap

- Scheduled jobs (launchd/cron hitting /api/views/{id}/run)
- Snapshot history + diff reports (what changed since last run)
- Additional columns (opportunity, branch, approval date)
- Admin-track migration: replace UI automation with OAuth JWT calls once a
  Connected App is granted
