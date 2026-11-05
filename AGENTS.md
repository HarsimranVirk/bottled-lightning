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

## Feature work goes through plan mode (mandatory)

Never start implementing a new feature request directly. Every feature — and any
change that alters behaviour, data shape, or an API contract — starts in **plan
mode**, and no code is written until the design is written down in `docs/`.

A plan is only complete when it contains all five of these, in this order:

1. **FR doc** — create or edit the feature's requirements document in `docs/`
   (follow the existing shape, e.g. `docs/FR-deviations.md`: status/version
   header, purpose, in-scope, out-of-scope, numbered requirement IDs `FR-x.y`,
   edge cases, acceptance criteria). Existing FR docs are edited in place
   (bump the version) rather than duplicated.
2. **Class design** — `docs/class-design-<feature>.md`: the classes, Protocols,
   workflow seams, ownership boundaries, and how the new pieces plug into
   `app/core` / `app/salesforce` / `app/jobs` / `app/workflows/*`. Every class
   named there must have a single clear responsibility and documented
   collaborators.
3. **Data model** — tables/columns, types, keys, indexes, one-shot vs. mutable
   semantics, retention, and the migration path. State which store owns the
   data (`data/app.db` SQLite, in-process state, or the browser session) and what
   happens to existing rows.
4. **API design** — endpoints and their request/response payloads (obeying the
   API conventions below), status/error cases, and the matching TypeScript
   types in `frontend/src/types.ts`.
5. **Decision register** — `docs/decisions-<feature>.md`: every locked design
   decision as a numbered entry (`D-01`, `D-02`, …) with the alternative that
   was rejected and why. It is the lock record described in "Implementation
   gate" below; implementation starts only once it is `LOCKED`.

Rules for the plan-mode phase:

- **All design decisions are recorded in `docs/` — the docs are the source of
  truth.** A decision that exists only in chat, a commit message, or a PR
  description does not count.
- Implementation starts **only after** the five documents exist and the user has
  approved the plan. Then `docs/refactor-plan-<feature>.md` (phases, cutover,
  rollback) is the execution order to follow.
- If implementation reveals a design gap, **stop and amend the doc first**, then
  continue. Never let `docs/` drift from the code: a behaviour change and its
  doc update ship in the same change.

### Design discussion and approval gate (mandatory)

A feature request is **not** approval of a design. Before changing behaviour,
data shape, an API contract, a Protocol/interface, a database table, or a
selector strategy, the agent must discuss the design with the user and wait for
explicit approval. This applies even when the user says "do it" in general
terms — the agent still proposes the concrete design first.

The discussion must happen **before** code or doc edits, and must be in plain
language, not a keyword dump:

1. **Explain what is being proposed and why.** Name the exact files, classes,
   fields, endpoints, and user-visible behaviour that would change. Say what
   stays the same.
2. **List the realistic alternatives** (including "do nothing") and the
   trade-offs: risk, effort, reversibility, effect on existing rows/data, and
   effect on the operator workflow.
3. **Ask a concrete question** and wait. A good question is "Approve option A
   (…), option B (…), or do you want a different shape?" — not "shall I
   proceed?".
4. **Do not implement, edit code, or rewrite design docs in the same turn as the
   proposal** unless the user has explicitly approved the proposal in that
   conversation. Approval must be explicit ("yes, implement option A", "go
   ahead with that design"), not inferred from an earlier feature request.
5. **If the user asks a question, reports a bug, or asks for an explanation, answer
   or investigate first.** Do not turn it into an unrequested code change.
6. **If a design gap appears mid-implementation, stop and ask.** Do not silently
   redesign, rename, or widen scope. Record the gap in the relevant `docs/` file
   only after the user approves the direction.
7. **Keep the user in the loop.** After approval, describe each implementation
   slice in detail before starting it, and do not bundle unrelated design
   changes into the same slice.

This gate is intentionally stricter than "plan mode": the four design documents
plus the locked decision register are the record, but the user's explicit
approval is what authorises implementation.

## Implementation gate — lock → build → walkthrough (mandatory)

Every implementation runs in three phases, in this order. A phase may not be
skipped, and the agent may not enter the next phase on its own authority. The
point is that the design is frozen before code exists and that the finished code
is explained back to the user in writing.

### Phase A — Design lock (before any code)

Writing the design docs is not the same as locking them. Until locked, every
decision is a proposal that can still change.

1. **Keep a decision register** at `docs/decisions-<feature>.md`. One row per
   decision, with a stable ID that is never reused or renumbered:

   | ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
   |---|---|---|---|---|---|
   | D-01 | … | … | … | files/tables/endpoints/classes | locked |

   The header carries `Status: PROPOSED` or `Status: LOCKED`, a version, the
   lock date, and who approved it. The register is a summary with pointers; the
   reasoning still lives in the four design docs.

2. **Present the register for approval.** Before locking, show the user the
   complete `D-xx` list in plain language (what changes, what stays, the rejected
   alternative) and ask a concrete question: "Lock D-01…D-12 as listed, or change
   which ones?" This is a separate approval from "the plan looks good".

3. **Lock only on explicit approval.** Then and only then write
   `Status: LOCKED`, the date, the approver, and bump the register version.
   Re-read the four design docs for contradictions first: two docs disagreeing
   is a design gap, not something to resolve in code. Update the ledger row to
   `locked` in the same edit so the state is visible from `docs/README.md`.

4. **Locked means frozen.** A locked entry is never edited in place. To change
   one, stop, add a dated amendment (`D-07a`, or a new `D-nn` that supersedes
   `D-07`), state what changed and why, get explicit approval, re-lock at the
   next version, and only then continue. Every amendment names the files and
   behaviour it invalidates.

5. **No lock, no code.** This includes "small" changes, renames, and
   "while we're in there" edits. If the lock is missing or stale, the correct
   action is to stop and ask, not to proceed and document afterwards.

### Phase B — Build in announced slices

Implement against the locked register, one slice at a time (see gate rule 7
above). Each slice names the `D-xx` / `FR-x.y` IDs it satisfies. If the code
disagrees with a locked decision, the code is wrong until an amendment is
approved. Move the ledger row to `building` when the first slice lands and to
`review` when the last one does.

### Phase C — Short guide plus live walkthrough (before "done")

Implementation is not finished when the tests pass. It is finished when the
user can follow what was built. The short guide is written down; the walkthrough
is a discussion with the user, not a document.

1. **`docs/guide-<feature>.md` — the short guide.** Aim for one to two pages,
   written for someone who has never seen the code. Required sections:
   - what the feature does, in operator language;
   - how to run and use it: exact commands, UI steps, and the endpoints it calls;
   - configuration/env vars and where state lives (which DB, which table);
   - the five most likely failure modes and what to do about each;
   - a pointer to the design docs and decision register.

2. **Live code walkthrough and review — in chat, with the user.** After the code
   is green, walk the user through it as a conversation. Do **not** write a
   walkthrough document; do not dump a wall of text and call it reviewed. The
   walkthrough must cover, in whatever order the user wants:
   - **File map** — every file added or changed, its responsibility, and the
     `D-xx` / `FR-x.y` IDs it implements.
   - **End-to-end traces with real examples** — one per user-visible flow,
     following the actual call chain: UI action or `curl` → route → service →
     repository/job → browser/DB → response. Quote real payloads and show the
     row/state that results. Example shape:
     `POST /api/syncs?workflow=deviations_z02` → `SyncService.request()` →
     `jobs` row with `kind=SYNC` → dispatcher → worker → list page → reconcile.
   - **Non-obvious code** — short excerpts with `file:line` and *why* it is
     written that way: the locking, the retry, the regex, the ordering
     constraint. Skip line-by-line narration of self-evident code.
   - **Failure paths** — expired session, timeout, ambiguity, cancelled job, bad
     payload: the exact status/error the user sees.
   - **Lock reconciliation** — `D-id → where implemented (file:line) → test that
     proves it`. Any row without a test or a file is a finding, said out loud.
   - **Deviations found during review** — must be none, or each one is an
     approved amendment. Anything else is an unreviewed design change and the
     agent must stop and raise it.
   - **Open risks and follow-ups** — stated plainly, not buried.

   Run it interactively: take one flow at a time, pause, invite questions, and
   follow the user's questions into whatever file or behaviour they care about.
   The review is done when the user has asked what they wanted and confirms they
   have the picture — not when the agent has finished talking. If the user's
   questions expose a gap, stop and go back through the approval gate.

3. **Update the ledger.** `docs/README.md` holds the index table
   (`feature | status | decision register | FR | walkthrough | guide | last
   updated`). Move the feature to `done` only when the guide exists and the live
   walkthrough has happened; record the walkthrough as `reviewed <date>` rather
   than a file link. Keep the guide and ledger current: a later behaviour change
   updates them in the same change, and earns a fresh walkthrough of the part
   that changed.

4. **Report back in chat.** The closing message links the guide, names the
   flows the walkthrough covered, and lists the gate results (ruff, mypy,
   typecheck, tests). A feature with no guide or no walkthrough is reported as
   incomplete, not as done.

### What "followed" means (self-check before finishing)

Before the final message, verify and state each of these:

- the decision register is `LOCKED`, with no orphan `PROPOSED` rows;
- every implemented behaviour traces to a `D-xx` (and an `FR-x.y` where one applies);
- code, guide, and ledger agree on the behaviour;
- the live walkthrough happened and covered the flows that changed — not that a
  file exists;
- gate commands were actually run and their results are quoted;
- no scratch files or temporary artefacts remain.

If any box is unticked, say so explicitly instead of implying completion.

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
    docs/              design docs and the source of truth for decisions:
                       FR-<feature>.md, class-design-<feature>.md,
                       data-model-<feature>.md, api-<feature>.md,
                       decisions-<feature>.md (the lock),
                       refactor-plan-<feature>.md (see "plan mode" above),
                       then guide-<feature>.md after implementation; the code
                       walkthrough happens as a discussion, not a doc;
                       README.md is the feature ledger
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
- Never close a task without the Phase C artefacts: `docs/guide-<feature>.md`,
  the live walkthrough with the user, and an updated `docs/README.md`. If the
  work changed behaviour, the guide and ledger move in the same change as the
  code, and the changed part gets walked through again — no walkthrough doc is
  written.
- After every edit, run ruff (`ruff check app/ frontend/`) and resolve **all** reported issues (including import sorting I001) before considering the change complete. The project uses ruff for linting/formatting; no ruff warnings may remain.
