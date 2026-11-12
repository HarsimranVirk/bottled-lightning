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

## Minimal changes: code is a liability

Every line we add has to be read, tested, migrated and maintained, so treat code
itself as a cost. For any task, change the **least** code that fully solves the
stated problem, and leave everything else alone.

- No speculative generality: no options, parameters, abstraction layers, or
  helpers added "in case we need them". Add them when a second caller exists.
- No scope creep: no drive-by renames, reformatting, dependency bumps, or
  "while we're in there" refactors. Unrelated cleanups get their own task.
- Prefer deleting code to adding it, and reuse the helper/pattern that already
  does the job before writing a new one. Duplicating three lines is often
  cheaper than a shared abstraction nobody else needs.
- A new file, table, column, endpoint, or setting needs to be justified by *this
  task*. If it cannot, it does not go in.
- Tests cover the behaviour the task changed, not every branch passed on the way.
- Minimal is not incomplete: the change still has to be correct, typed,
  documented (see below), and verified. Cutting corners on those is not
  "smaller", it is broken.

If you think a larger change is genuinely warranted, say so and get agreement
first — do not fold it into the current task.

## Feature work: plan → review → implement

Every feature — and any change that alters behaviour, data shape, or an API
contract — follows these steps, in this order.

1. **Write a solid implementation plan.** Before touching code, work out the
   concrete change: the files, classes, functions, DB tables/columns, endpoints,
   TypeScript types, and user-visible behaviour that would change, plus what
   stays the same, the main risks, and how the result will be verified (tests,
   commands, manual check). Keep it as long as the change deserves — a few
   paragraphs for a small change, more for a large one — but be specific enough
   that the user can spot a wrong assumption before code exists.

2. **Review and discuss it with the user.** Present the plan in plain language
   (what changes, what stays, realistic alternatives where they matter) and ask
   a concrete question. Do not implement in the same turn as the proposal;
   wait for explicit approval. If the user asks a question, reports a bug, or
   asks for an explanation, answer or investigate first — do not turn it into
   an unrequested code change.

3. **Implement in small slices.** One slice at a time, each small enough that
   the diff is easy to verify and validate in a single turn. Say what a slice
   will change before starting it. Do not bundle unrelated changes, renames, or
   "while we're in there" edits into the same slice. If implementation reveals
   the plan was wrong, stop and say so before changing direction. Keep each
   slice to the smallest code change that fully solves its part (see "Minimal
   changes" above).

4. **Report each slice before moving on.** After a slice lands, give a short
   summary of the code changes plus a walkthrough of what changed and how to
   validate it:
   - which files changed and what each one now does;
   - the user-visible flow or call chain affected (entry point → layers →
     result), with concrete inputs/outputs;
   - anything non-obvious and why it is written that way;
   - exact validation steps: commands to run, UI clicks, or `curl` calls, and
     the expected output/state;
   - the gate results for that slice (ruff, mypy, typecheck, tests).

   Then continue with the next slice unless the user asks to pause or validate
   first.

Existing design records in `docs/` (FR docs, class design, data model, API
design, decision registers, refactor plans, guides) remain useful reference
material for larger features, and should be kept consistent with the code when
they exist. They are no longer a required gate: use them when a change is big
enough to need a written record, and skip them for routine work.

## Code documentation (required for every class and method)

Every module, class, Protocol, function, and method in `app/` and `tests/` gets a
docstring. It must be genuinely explanatory, not a restatement of the name:

- **What it is / does**, in one or two sentences of plain language.
- **When and how it is called** — which layer invokes it (route, job worker,
  sync loop, another class), whether it is lazy/one-shot, and any threading,
  blocking, or ordering constraints (e.g. "runs on a worker thread", "must be
  called after `Session.ensure()`").
- **Arguments and return value** semantics, including units/formats (months,
  Indian-grouped amounts, UTC timestamps) and `None` meanings.
- **Raises / failure modes** — what surfaces to the caller versus what is logged
  and swallowed.
- **A short usage example** where the call shape is not obvious (a 2-4 line
  snippet, not a full program). Pydantic models and `TypedDict`s can document
  fields inline with comments if a docstring would be redundant.

Keep docstrings current: touching a signature or behaviour means updating its
docstring in the same change.

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
SF. Detail extraction is one-shot (`work_items.extracted_at`): only values that
were never visited are auto-extracted, and missing page-ref kinds do NOT trigger
a re-scrape. `POST /api/syncs?workflow=deviations_z02` requests an immediate list
refresh; the watcher also refreshes every `SF_RESYNC_INTERVAL_SECONDS`.

## Architecture

    app/config.py      settings (org URLs, data dir, workers, refresh interval,
                       update policy; env-overridable)
    app/db/            SQLite connection + schema/migrations (data/app.db)
    app/core/          domain models, statuses, field/catalogue types, workflow
                       seam, registry, repositories
    app/salesforce/    async browser runtime, session snapshot/reload, tabs,
                       list page, login CLI, object adapters
    app/jobs/          persisted queue: dispatcher, worker, auth gate, logger
    app/pipeline/      list watcher, reconciler, closure resolver
    app/api/           FastAPI app, plural-noun routes, schemas, services
    app/workflows/     workflow implementations; deviations_z02 is the only one
                       today (catalog, description, product map, adapters,
                       extraction, submission)
    app/devtools/      dev-only read-only DB explorer service and exports
    app/maintenance.py manual retention policy (current 24 h incl. terminal jobs/logs,
                       history 90 d; sync_runs ring in SyncRunRepository)
    app/utils/         shared async DOM helpers and the JsonValue type
    app/main.py        FastAPI app + `main()` entry point (serves frontend/dist)
    app/updater.py     GitHub-release self-update: check → verify wheel
                       (version + sha256) → pip install → re-exec
    launchers/         start.command (macOS), start.bat (Windows) + release
                       lookup helper — the double-click install path
    pyproject.toml     wheel packaging; frontend/dist force-included as app/web
    .github/workflows/release.yml  tag → build wheel + launchers → release
    tests/             backend unit tests (no network, no browser)
    frontend/          React (Vite) + Salt DS SPA (TypeScript, strict) —
                       home/auth + deviations deck; API types in src/types.ts
    docs/              reference docs: existing FR / class-design / data-model
                       / api / decisions / refactor-plan records,
                       guide-<feature>.md, dev-tools.md, and README.md (feature
                       ledger). Used for larger features; not a required gate
                       (see "Feature work" above)
    data/              runtime state in a checkout (gitignored): app.db (includes
                       session snapshots), sf_profile_login/, sf_profile_worker/;
                       installed builds use the OS app-data dir

## Commands

    source .venv/bin/activate
    python -m app.main                     # backend on 0.0.0.0:8765 (init DB, print LAN URL)
    python -m app.main --no-update          # skip the GitHub update check
    SF_DEV_TOOLS=0 python -m app.main       # disable the hidden /dev/db explorer

Equivalent direct uvicorn form (DB auto-inits on startup either way):

    uvicorn app.main:app --host 0.0.0.0 --port 8765
    python -m app.salesforce.login          # one manual login when session expires
    python -m app.salesforce.login --reset  # nuke saved session and re-login
    python -m unittest discover -s tests    # backend unit tests
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
  `setdefault`/`getattr` patterns that defeat type narrowing. Bare `dict`/`list`
  are forbidden; always parameterize (`dict[str, int]`, `list[str]`). The
  frontend is TypeScript (`.ts`/`.tsx`) with `strict` on and shared API payloads
  in `frontend/src/types.ts`; `npm --prefix frontend run typecheck` must pass.
  `npm run build` runs the typecheck, so a type error blocks a release.
- **Never escape types. No exceptions.** `Any` and `object` are forbidden
  entirely — do not import or use them anywhere in `app/` or `tests/`.
  `cast`, `# type: ignore`, `# pyright: ignore`, and any other type-checker
  suppression are forbidden too. Model data with concrete types,
  `TypedDict`, `Protocol`, `Callable`, generics, or real Pydantic models, and
  **fix the underlying type error** rather than silencing it. If an
  unavoidable upstream/stub gap truly blocks you, raise it with the user and
  document the decision in `docs/` — do not suppress it unilaterally.
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
- Frontend dev covers home/auth, the review deck, accepted history, the jobs table and
  the validate-only submit flow. Backend workflows still come first; the frontend follows
  the API contract.
- Playwright's async API is used on the dedicated browser runtime thread/loop; jobs run
  through the async dispatcher. Don't introduce `sync_playwright`, a second event loop, or
  worker-thread browser calls without a redesign discussion.
- Keep the frontend aligned with the generated API types; no client-side business rules.
- The DB explorer is a hidden dev link at `/dev/db`, enabled by default. Keep it out of
  the main navigation, localhost-only unless `SF_DEV_TOOLS_ALLOW_REMOTE=1` is explicit,
  and never expose or query the `sessions` table (the read-only authorizer must keep
  denying it). `SF_DEV_TOOLS=0` is the explicit off switch. CSV/XLSX exports use the same
  guard. See `docs/dev-tools.md`.
- Retention is manual: the DB explorer's current purge keeps 24 hours of work items,
  their terminal jobs and those jobs' logs; the history purge keeps 90 days of approved
  snapshots. Keep the cutoffs fixed server-side, keep both actions confirmed and dry-run
  first, and never let one purge touch the other store, `sessions`, or an item/job that is
  still active. The one automatic deletion is the `sync_runs` ring in
  `SyncRunRepository.record()` — newest 20 rows per workflow, no reader beyond the newest.
- Every data table uses the shared table-filter pattern: a text (or range) input plus a
  multiselect dropdown with checkboxes for exact values. Empty selection means all;
  selected values are OR within a column, columns compose with AND, and the text and
  selected values in one column also compose with AND. Date and duration ranges use the
  shared range variant instead of a checkbox list. New tables must reuse
  `frontend/src/components/TableFilter.tsx` and `TableRangeFilter.tsx`, not bespoke
  filter cells. Server-paginated tables must send every selected value to the server so
  the total and later pages stay correct.
- Clean up any temporary/scratch files created during work, wherever on the system (e.g. /tmp, the OS temp dir, scratch dirs, worktrees) before finishing; don't leave throwaway scripts or artifacts behind.
- Extraction code changes require re-verifying the header-total cross-check.
- Close a task by reporting what changed, why, and the quoted gate results
  (ruff, mypy, typecheck, tests). If a change altered behaviour in a way
  operators or future maintainers need to know, update the relevant `docs/`
  guide or notes in the same change.
- After every edit, run ruff (`ruff check app/ frontend/`) and resolve **all** reported issues (including import sorting I001) before considering the change complete. The project uses ruff for linting/formatting; no ruff warnings may remain.
