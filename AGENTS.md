# AGENTS.md — bottled-lightning

Guidance for agents (and humans) working in this repository. Read this before
touching anything.

## What this project is

A local FastAPI + Playwright webapp that extracts data from Salesforce
Lightning list views we don't have REST API access to. Backend is Python
(threads, SQLite). The React (Vite) frontend uses J.P. Morgan's open-source
**Salt DS** design system (`@salt-ds/core`, `@salt-ds/theme`, `@salt-ds/icons`);
the home page handles session auth (manual-login trigger, snapshot status,
localStorage mirror).

## Critical Salesforce org facts (learned through many failures — trust these)

1. **Session cookies are host-locked.** The org locks Lightning sessions to
   the domain they were created on (`hffc.lightning.force.com`). REST API
   endpoints reject this session even as `Authorization: Bearer` or when
   replayed as a `Cookie` header (`INVALID_SESSION_ID`). Server-side API
   automation is impossible for this user. Do not retry this path.
2. **`sid` cookies are session-only.** Salesforce drops them on every browser
   restart. The ONLY way to survive restarts is snapshotting via Playwright's
   `storage_state()` right after a manual login and injecting those cookies
   (`ctx.add_cookies`) at every launch. The snapshot is stored in the
   **`sessions` table of `data/app.db`** (authoritative store); the old
   file-based `data/auth.json` is still read as a legacy fallback.
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

## Workflow notes (deviation deck)

4. The bare "EMI-" line in the description is the **pre-calculated EMI** —
   it must NOT be stored. The deck's EMI field is **"EMI & other fixed
   payments incl. HFFC Loan"**, parsed from the `EMIs & other …-…` line
   (both `EMIs & other fixed pmts inc HFFC Loan-…` and
   `EMIs & other HFFC Loan-…` shapes occur). Amount fields display Indian
   grouping (25,50,000); tenure is stored in months.

## Architecture

    app/config.py      settings (org URLs, data dir; env-overridable)
    app/browser.py     Playwright session manager + `python -m app.browser --login`
    app/extractors.py  strategies: printable view (primary), Show-more +
                       scroll drain (fallback); count cross-check vs header
    app/jobs.py        ThreadPool job runner (serial: 1 browser at a time)
    app/store.py       SQLite (data/app.db — general-purpose store): views,
                       jobs, job_rows, latest_values, session_events,
                       sessions (auth snapshots)
    app/routes.py      REST endpoints under /api
    app/main.py        FastAPI app
    frontend/          React (Vite) scaffold — DO NOT develop right now
    data/              runtime state (gitignored): db, auth.json, sf_profile

## Commands

    source .venv/bin/activate
    python -m app.main                     # backend on 0.0.0.0:8765 (init DB, print LAN URL)

Equivalent direct uvicorn form (DB auto-inits on startup either way):

    uvicorn app.main:app --host 0.0.0.0 --port 8765
    python -m app.browser --login           # one manual login when session expires
    python app.browser --login --reset      # nuke saved session and re-login

Jobs that fail with "session expired" mean the org's inactivity timeout hit a
saved session — run the manual login once; snapshots refresh automatically.

## Rules

- NEVER commit `data/` (the whole dir is gitignored): `app.db` now contains
  the live session token (sessions table) — equivalent to the account
  password. Same for `auth.json` leftovers and `sf_profile/`.
- Keep Python 3.9 compatibility (`Optional[int]`, not `int | None`).
- Frontend dev is limited to home/auth (views/jobs UI not built yet) — backend
  workflows still come first.
- Playwright sync API is used; jobs run in worker threads. Don't use
  asyncio APIs here without a redesign discussion.
- Don't expand the frontend until the backend workflows are done and stable.
- Extraction code changes require re-verifying the header-total cross-check.
