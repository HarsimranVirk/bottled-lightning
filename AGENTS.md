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

Queued deviations are treated as immutable in practice — nobody edits them in
SF. Detail extraction is one-shot (`deviation_details.extracted_at`): only
values that were never visited are auto-extracted, and missing page-ref kinds
do NOT trigger a re-scrape. `POST /api/deviations/jobs?refresh=true` forces a
full re-scrape when you actually need one.

## Architecture

    app/config.py      settings (org URLs, data dir, update policy; env-overridable)
    app/browser.py     Playwright session manager + `python -m app.browser --login`
    app/deviations/    clubbed extractors shared by z01-z04 (common, list_view,
                       deviation_record, opportunity + strategies; composite
                       pattern) + base (WorkflowProfile, registry, product map)
    app/deviations_zNN/ thin workflow packages: PROFILE + own updaters/ (zNN-specific)
    app/cancellations/ separate workflow (own extractors + updaters)
    app/jobs.py        ThreadPool job runner (serial: 1 browser at a time);
                       consumes the resync snapshot instead of re-visiting the list
    app/sync.py        continuous queue resync loop: visits the list view every
                       RESYNC_INTERVAL_SECONDS (30s), reconciles latest_values,
                       keeps the ListSnapshot that extraction jobs reuse
    app/store.py       SQLite (data/app.db — general-purpose store): views,
                       jobs, job_rows, latest_values, session_events,
                       sessions (auth snapshots)
    app/routes.py      REST endpoints under /api (incl. /api/updates)
    app/main.py        FastAPI app + `main()` entry point (serves app/web or
                       frontend/dist)
    app/updater.py     GitHub-release self-update: check → verify wheel
                       (version + sha256) → pip install → re-exec
    launchers/         start.command (macOS), start.bat (Windows) + release
                       lookup helper — the double-click install path
    pyproject.toml     wheel packaging; frontend/dist force-included as app/web
    .github/workflows/release.yml  tag → build wheel + launchers → release
    tests/             updater unit tests (no network)
    frontend/          React (Vite) + Salt DS SPA (TypeScript, strict) —
                       home/auth + deviations deck; API types in src/types.ts
    data/              runtime state in a checkout (gitignored): db, auth.json,
                       sf_profile; installed builds use the OS app-data dir

## Commands

    source .venv/bin/activate
    python -m app.main                     # backend on 0.0.0.0:8765 (init DB, print LAN URL)
    python -m app.main --no-update          # skip the GitHub update check

Equivalent direct uvicorn form (DB auto-inits on startup either way):

    uvicorn app.main:app --host 0.0.0.0 --port 8765
    python -m app.browser --login           # one manual login when session expires
    python app.browser --login --reset      # nuke saved session and re-login
    python -m unittest discover -s tests    # updater tests
    mypy --strict app tests                 # Python typecheck (all code typed)
    npm --prefix frontend run typecheck     # TypeScript typecheck (strict)
    python -m build --wheel                 # after `npm --prefix frontend run build`

Jobs that fail with "session expired" mean the org's inactivity timeout hit a
saved session — run the manual login once; snapshots refresh automatically.

## API conventions

- REST naming: endpoints use **plural nouns only** (no verbs) under `/api`. Use
  HTTP methods for actions (`GET` list/read, `POST` create, `PATCH` update,
  `DELETE` remove) and path parameters to select a single object
  (`/api/views/{id}`). Filters, pagination and format selection go in query
  parameters (`?status=`, `?limit=`, `?format=csv`, `?decision=`). Avoid
  verb segments like `/run`, `/login`, `/check`, `/apply`; model them as
  sub-resources instead (`/api/views/{id}/jobs`, `/api/sessions`,
  `/api/updates/checks`).

## Rules

- NEVER commit `data/` (the whole dir is gitignored): `app.db` now contains
  the live session token (sessions table) — equivalent to the account
  password. Same for `auth.json` leftovers and `sf_profile/`.
- Target Python 3.14 (`.python-version`, `requirements.txt`). **The project is
  completely typed — keep it that way.** Every function and method in `app/`
  and `tests/` (including `-> None`) needs annotations, and
  `mypy --strict app tests` must pass. Code must also be clean under
  `basedpyright`/`pyright` (Pylance) — resolve all reported diagnostics,
  including "X is not a known attribute of None" and similar narrowing
  issues; prefer explicit `None` checks / `isinstance` guards over
  `setdefault`/`getattr` patterns that defeat type narrowing. **`Any` is
  forbidden entirely** — do not import or use it anywhere in `app/` or
  `tests/`. Use concrete types, `TypedDict`, `Protocol`, `Callable`,
  `object`, or `Unknown`-style explicit types instead. Bare `dict`/`list`
  are also forbidden; always parameterize (`dict[str, int]`,
  `list[str]`). The frontend is TypeScript
  (`.ts`/`.tsx`) with `strict` on and shared API payloads in
  `frontend/src/types.ts`; `npm --prefix frontend run typecheck` must pass.
  `npm run build` runs the typecheck, so a type error blocks a release.
- **Never escape types.** Do not weaken or bypass typing by using `Any`,
  `object`, `cast`, `# type: ignore`, type-checker `noqa` suppressions, or
  `response_model=None` hacks merely to make code pass. Model data with
  concrete types / Pydantic models / `TypedDict` / `Protocol` instead, and
  fix the underlying type error rather than silencing it. `cast` and
  `# type: ignore` are only acceptable with a written justification in a
  comment.
- Releases are wheels: bump `__version__` in `app/__init__.py`, tag `vX.Y.Z`
  (the workflow fails on a mismatch) and let CI build. Never edit the version
  only in `pyproject.toml` — it is dynamic and read from `app/__init__.py`.
- `frontend/dist` is gitignored but must exist before `python -m build`;
  the wheel serves it from `app/web`. Don't make the app read `frontend/` at
  runtime from an installed build.
- Self-update only installs from GitHub-hosted URLs, verifies the wheel's
  `__version__` against the release tag and (when GitHub provides one) the
  sha256 digest. Keep those guards; a bad release must fail without breaking
  the running app (`/api/updates` reports it).
- The updater must never apply while a job or login is running, and must never
  raise at boot. A missing repo/release is a normal "up to date".
- Installed runs keep state in the OS app-data dir; only source checkouts use
  `./data`. Keep `SF_DATA_DIR` as the override.
- `launchers/start.bat` must stay CRLF and `start.command` executable
  (`.gitattributes` handles both). The launcher only bootstraps — updates are
  the app's job.
- Frontend dev is limited to home/auth (views/jobs UI not built yet) — backend
  workflows still come first.
- Playwright sync API is used; jobs run in worker threads. Don't use
  asyncio APIs here without a redesign discussion.
- Don't expand the frontend until the backend workflows are done and stable.
- Clean up any temporary/scratch files created during work, wherever on the system (e.g. /tmp, the OS temp dir, scratch dirs, worktrees) before finishing; don't leave throwaway scripts or artifacts behind.
- Extraction code changes require re-verifying the header-total cross-check.
- After every edit, run ruff (`ruff check app/ frontend/`) and resolve **all** reported issues (including import sorting I001) before considering the change complete. The project uses ruff for linting/formatting; no ruff warnings may remain.
