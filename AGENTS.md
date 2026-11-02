# AGENTS.md — Salesforce UI Automation Webapp

Guidance for agents (and humans) working in this repository. Read this before
touching anything.

## What this project is

A local FastAPI + Playwright webapp that extracts data from Salesforce
Lightning list views we don't have REST API access to. Backend is Python
(threads, SQLite); the React (Vite) frontend is **paused** — workflows/backed
automation comes first.

## Critical Salesforce org facts (learned through many failures — trust these)

1. **Session cookies are host-locked.** The org locks Lightning sessions to
   the domain they were created on (`hffc.lightning.force.com`). REST API
   endpoints reject this session even as `Authorization: Bearer` or when
   replayed as a `Cookie` header (`INVALID_SESSION_ID`). Server-side API
   automation is impossible for this user. Do not retry this path.
2. **`sid` cookies are session-only.** Salesforce drops them on every browser
   restart. The ONLY way to survive restarts is snapshotting via Playwright's
   `storage_state()` right after a manual login, saving to `data/auth.json`,
   and injecting those cookies (`ctx.add_cookies`) at every launch.
3. **Extraction must use Playwright's selector engine** (`get_by_text`,
   locators). This org runs Lightning in a mode where `document.*` JS sees
   almost nothing of the data table (locked/synthetic shadow DOM);
   `page.evaluate()`-based scanning silently returns 0. The same elements ARE
   visible to Playwright text locators.
4. **Use the Printable View, not scrolling.** Virtualized Lightning tables
   only keep rendered rows in the DOM. Clicking "Printable View" opens a
   popup (`https://hffc.my.salesforce.com/a2f/x?fcf=...`) that renders ALL
   rows at once — headless-safe with injected cookies. Use it as the primary
   strategy; scrolling is a fallback only.
5. **Regex trap:** deviation numbers look like `Deviation-28102026-484106` —
   the middle segment is 8 digits (DDMMYYYY). Patterns like
   `Deviation-\d{2,4}-\d+` never match and produce silent zero results.
   Current safe pattern: `Deviation-\d+-\d+`.
6. The object behind "Loan Deviations" is `Consumer_Loan_Deviation__c`
   (record key prefix `a2f`). List view in use:
   `filterName=Z2_Loan_para_pricing1` → `fcf=00BNo000006HMof`.
7. **Cross-check always:** the list header shows "N items". Report (and flag)
   a mismatch when extracted count ≠ N. This caught our worst failures.

## Architecture

    app/config.py      settings (org URLs, data dir; env-overridable)
    app/browser.py     Playwright session manager + `python -m app.browser --login`
    app/extractors.py  strategies: printable view (primary), scroll (fallback)
    app/jobs.py        ThreadPool job runner (serial: 1 browser at a time)
    app/store.py       SQLite (stdlib sqlite3): views, jobs, job_rows, latest_values
    app/routes.py      REST endpoints under /api
    app/main.py        FastAPI app
    frontend/          React (Vite) scaffold — DO NOT develop right now
    data/              runtime state (gitignored): db, auth.json, sf_profile

## Commands

    source .venv/bin/activate
    uvicorn app.main:app --port 8765        # backend
    python -m app.browser --login           # one manual login when session expires
    python app.browser --login --reset      # nuke saved session and re-login

Jobs that fail with "session expired" mean the org's inactivity timeout hit a
saved session — run the manual login once; snapshots refresh automatically.

## Rules

- NEVER commit `data/`, `auth.json`, `sf_profile/` (contains a live session
  token — equivalent to the account password).
- Keep Python 3.9 compatibility (`Optional[int]`, not `int | None`).
- Playwright sync API is used; jobs run in worker threads. Don't use
  asyncio APIs here without a redesign discussion.
- Don't expand the frontend until the backend workflows are done and stable.
- Extraction code changes require re-verifying the header-total cross-check.
