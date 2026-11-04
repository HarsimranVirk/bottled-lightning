# Refactor Plan — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v2 |
| **Date** | 2026-11-04 |
| **Target design** | `docs/class-design-deviations.md` (v2, workflow abstraction) |
| **Requirements** | `docs/FR-deviations-v2.md` (v2.1) |

> v2 of this plan adds the workflow seam from the v2 class design: core mechanism in
> `app/core`, `app/salesforce`, `app/pipeline`, `app/jobs`; deviations lives in
> `app/workflows/deviations_z02` and is one implementation of `ExtractionPipeline` /
> `SubmissionPipeline`. Nothing in this plan implements a second workflow — it only keeps
> the door open.

---

## 1. Strategy

**Branch-based cutover, not a strangler.** The async browser migration invalidates every
sync Playwright call site, so keeping the old and new browser stacks side by side would
mean porting each extractor twice. Instead: freeze features on `main`, build the new stack
on a branch in dependency order, cut over in one merge, delete the old code in the merge
commit.

Rollback is the tag `pre-deviations-v2` on the current `main`. The local `data/app.db` is
disposable (O-4), so there is no data migration to reverse.

Rules for the whole effort:

- Every phase ends with `mypy --strict app tests`, `ruff check app/`, and the phase's own
  tests green.
- No phase adds a feature that is not in the FR doc.
- Each phase is one or more self-contained commits; nothing is left half-wired at the end
  of a phase.
- The core/workflow split is established in Phase 1, before any pipeline code exists, so
  no later phase has to "retrofit extensibility". A second workflow must be addable by
  creating `app/workflows/<name>/` only.
- The app is allowed to be non-functional on the branch between Phase 2 and Phase 7. It is
  **not** allowed to be non-functional on `main`.

Rough sizing assumes one focused developer: **~22–27 working days**, of which Phases 3 and
6 (adapters, submit) are the long poles because they are UI-selector work.

**Progress:** Phases 0–3 are done on branch `refactor/deviations-v2` (core domain,
schema v2, repositories, workflow seam, Z02 catalog + description parser, async browser
runtime, session snapshot/expiry, `ListPage`, login CLI, six Z02 adapters and the
`DeviationsZ02Extraction` pipeline). Phases 4–9 are not started.

Phase 2's live gate is only half-verified: the runtime boots, injects cookies, navigates
and correctly reports an expired session, and `ListPage` was verified end-to-end against a
local fake list page (header total, links, printable-view popup, validity rule). A real
run needs `python -m app.salesforce.login` first.

Also landed in Phase 1/2: `Database.migrate()` refuses a pre-v2 database instead of
half-migrating it (`legacy schema detected … needs a fresh database`), which makes O-4 an
explicit decision rather than a silent corruption.

---

## 2. What exists today

| Area | File(s) | Lines | Verdict |
|---|---|---|---|
| Settings | `app/config.py` | 63 | reshape into `Settings` |
| Browser session | `app/browser.py` | 205 | rewrite async (`salesforce/runtime.py`, `session.py`, `tabs.py`) |
| Session persistence | `store.py` (`sessions`, `session_events`) | ~80 | move to `repo/sessions.py` |
| Deviation extraction | `deviations/extractors/**` | ~700 | port to `salesforce/adapters/**` + `pipeline/extract.py` |
| Workflow registry | `deviations/base.py` | 65 | delete (`WorkflowProfile` no longer needed) |
| Per-workflow packages | `deviations_z01..z04/**` | ~200 | delete (z01/z03/z04 stubs; z02 pipeline superseded) |
| Cancellations | `app/cancellations/` | 2 | delete now; returns later as `app/workflows/cancellations/` |
| Job runner | `app/jobs.py` | 295 | rewrite (`jobs/dispatcher.py`, `worker.py`) |
| Resync loop | `app/sync.py` | 333 | rewrite (`pipeline/watcher.py`, `reconciler.py`) |
| Store | `app/store.py` | 788 | split into `repo/*` + `db/*` |
| Routes | `app/routes.py` | 430 | split into `api/routes/*` |
| API types | `app/types.py` | 233 | split: DTOs → `api/schemas.py`, domain → `domain/models.py` |
| Deviation types | `app/deviations/types.py` | 56 | delete (duplicates `types.py`) |
| Frontend | `frontend/src/**` | ~700 | rewrite views, keep Salt DS + auth page |
| Updater | `app/updater.py` | 298 | unchanged |
| Launchers / packaging | `launchers/`, `pyproject.toml` | — | unchanged, version bump only |

Existing behaviours that must survive the port (they encode hard-won facts):

- Session snapshot → SQLite, cookies injected at launch, legacy `auth.json` fallback.
- Description parsing, including excluding the bare `EMI-` line.
- CL-contract product matching via `CL_CONTRACT_PRODUCT_MAP`.
- LMS 2.0 shadow-DOM row scraping (`_scrape_lms_rows`).
- Ambiguity → skip with reason, never a guess.
- Header-total cross-check.
- Playwright text locators, not `page.evaluate` DOM scans (except the LMS shadow DOM case).

---

## 3. Phases

### Phase 0 — Baseline and safety net (1 day)

- Tag `pre-deviations-v2`.
- Freeze features; no functional work on `main` during the refactor.
- Add unit tests for the pure logic that is about to be rewritten:
  `parse_description_fields` (all four fields + bare-`EMI-` exclusion),
  `CL_CONTRACT_PRODUCT_MAP` lookups, and the header-total rule.
- Record the current HTTP surface (`GET /api/...` inventory) so the new API can be diffed
  against it.
- Decide O-3 and O-4 so later phases don't stall.

**Gate:** tests green on `main`; baseline typecheck/lint recorded.

### Phase 1 — Core domain, persistence, workflow seam (4 days)

- `config.py` → frozen `Settings` + `load_settings()`. Keep env var names where they are
  already documented (`SF_DATA_DIR`, `SF_ORG_BASE`, `SF_RESYNC_INTERVAL_SECONDS`); rename
  `SCRAPE_WORKERS` → worker count in `Settings`.
- `db/connection.py`, `db/schema.py` (workflow-scoped v2 DDL from the design doc),
  `Database.migrate()`.
- `core/models.py`, `core/status.py`, `core/field.py`, `core/errors.py`.
- `core/workflow.py` — `Workflow` spec and the `ExtractionPipeline` / `SubmissionPipeline`
  protocols; `core/registry.py` — `WorkflowRegistry`.
- `core/repo/*` for work items, fields, attributes, refs, jobs, sessions, sync runs, events.
- `app/workflows/deviations_z02/catalog.py` — `DeviationObject` + `FIELD_CATALOG`
  (placeholder targets until O-1) and an `__init__.py` that registers a `Workflow` whose
  pipelines are not yet implemented (a `NotImplementedPipeline` that raises, used only by
  tests).
- Tests: repository round-trips on a temp DB; transition table rejects illegal moves;
  `transition()` refuses terminal status under an active lease; the `jobs_active` partial
  unique index prevents two active jobs for one `(workflow, item)`; a **fake workflow**
  proves the registry can carry a workflow and its pipelines without core changes.

**Gate:** `Database.migrate()` on an empty file produces v2; repo + registry tests green;
`grep -r "deviations" app/core app/salesforce app/pipeline app/jobs` returns nothing.

### Phase 2 — Browser runtime (3–4 days)

- `salesforce/runtime.py`: dedicated thread + `asyncio` loop, one persistent context,
  `run()` / `spawn()` bridges.
- `salesforce/session.py`: snapshot injection, `ensure()` (raises `SessionExpired`),
  `reload()` after manual login, `save_from()`.
- `salesforce/tabs.py`: `TabGroup` with `open()` context manager and per-tab timeout.
- `salesforce/list_view.py`: `refresh()`, `read()`, and the pure `is_valid_sample`.
- Manual login path: `python -m app.salesforce.login` (replaces
  `python -m app.browser --login`), headed browser, snapshot saved to `sessions`, plus a
  `--reset` flag.
- Smoke script (not shipped) that opens the list, prints header total + row count, and
  closes. This is the first real proof of the async migration.

**Gate:** smoke script returns a valid sample against the live org with injected cookies;
no `sync_playwright` anywhere in the new tree; `ruff`/`mypy` clean.

### Phase 3 — Deviations adapters + extraction (4–5 days)

- `salesforce/adapters.py`: `ObjectAdapter` protocol, `AdapterRegistry`.
- `workflows/deviations_z02/adapters/*`: port the six adapters, preserving selectors and skip
  semantics. The LMS 2.0 adapters share the shadow-DOM row scraper.
- `workflows/deviations_z02/description.py`: move the parser, keep the bare-`EMI-` rule.
- `workflows/deviations_z02/extraction.py`: implements `ExtractionPipeline` — deviation
  record first, then the opportunity / CL-contract / collateral related lists in parallel
  on one `TabGroup`; persist fields, attributes, refs; return `EXTRACTED` or `SKIPPED`.
- Wire the real workflow object in `app/workflows/deviations_z02/__init__.py` (replacing the
  Phase 1 placeholder pipeline for extraction).
- Tests with fake adapters: ordering, skip propagation, idempotent re-run when
  `extracted_at` is set, no core changes required to run a second fake workflow.

**Gate:** a single deviation extracts end-to-end into the v2 tables through the registry;
skip reasons match today's strings; header cross-check still reported.

Status: implemented, verified with fake adapters (ordering, persistence, skips,
idempotency, force, `SessionExpired` propagation). The six adapters are faithful async
ports of the working sync extractors, but have not been run against the live org yet —
that needs a valid session and is the first thing to check once login is refreshed.

### Phase 4 — Queue, dispatcher, worker (2–3 days)

- `repo/jobs.py` claim/lease/requeue-stale/heartbeat; `jobs/lease.py`.
- `jobs/dispatcher.py`: claim loop, `asyncio.Semaphore(workers)`, pause on `AuthGate`.
- `jobs/worker.py`: `TabGroup` lifecycle, phase markers, `JobLogger`, exception
  translation, guaranteed lease release.
- Worker routes `(job.workflow, job.kind)` through `WorkflowRegistry` to
  `workflow.extraction` / `workflow.submission` — no if/else on workflow name.
- `AuthGate`.

**Gate:** `EXTRACT` jobs drain from the queue with N in flight; killing the process
mid-job and restarting requeues the stale lease without duplicating work; session expiry
parks jobs as `BLOCKED_AUTH` and resumes after re-login.

### Phase 5 — Watcher, reconciliation, closure (2 days)

- `pipeline/watcher.py`: one `ListWatcher` per registered workflow, 30 s loop on its own
  dedicated page, `refresh()` → `read()`.
- `pipeline/reconciler.py`: generic valid-sample gate, add/touch/absent, `workflow.map_row`
  for list-visible attributes, epoch handling.
- `pipeline/closure.py`: generic `ClosureResolver` (the decision table from FR-2.8 /
  FR-6.11) — no workflow-specific branching.
- Tests: invalid sample mutates nothing; absent + no lease → terminal; absent + lease →
  `absent_pending` → terminal on release; `proposed` never overwritten; reappearance
  starts a new epoch; the same tests pass with the fake workflow from Phase 1.

**Gate:** a full add → extract → disappear cycle is driven by the watcher alone, with
`sync_runs` showing valid/invalid cycles and warnings.

### Phase 6 — Deviations submission (4–5 days) — **blocked on O-1, O-2**

- `workflows/deviations_z02/submission.py`: implements `SubmissionPipeline` —
  precheck → apply → validate → execute, returning `COMPLETED` / `ALREADY_CLOSED` /
  `FAILED`.
- Per-target-object apply using `FieldTarget` groups; read-back verification; presence
  check twice (start of apply, last validation step).
- Final action: click `Implement`, modal confirm, observe page state, record
  `execute_attempted_at` / `execute_confirmed_at`.
- Idempotency: phase markers, applied values persisted per field, final action guarded.
- `work_item_edits` audit writes at submit time.
- Tests with fake adapters/pages: never execute after a failed validation; never execute
  when absent (→ `ALREADY_CLOSED`); retry after crash does not double-apply; partial
  failure leaves accurate per-field truth.

**Gate:** a deviation with edited values goes apply → validate → implement against SF
(test deviation only), and the resulting status is `COMPLETED` (rendered as
"Implemented") with a matching audit trail.

### Phase 7 — API rewrite (2 days)

- `api/schemas.py` DTOs; `api/services.py` (`WorkItemService`, `AdminService`);
  `api/routes/workflows.py` exposing `make_router(workflow)` mounted once per registered
  workflow, plus the shared `jobs`/`sessions`/`syncs`/`workers` routers.
- Remove every legacy alias route and the `views`/`job_rows`/`latest_values` concepts.
- Keep `updater` endpoints as-is, re-mounted under the new router.
- Test with FastAPI `TestClient`: route inventory matches the design table; a second fake
  workflow mounted through `make_router` exposes the same surface with zero handler code;
  no handler touches Playwright directly.

**Gate:** frontend builds against the new types; no behaviour change without a
corresponding FR; adding a workflow requires no route code.

### Phase 8 — Frontend (3–5 days)

- `types.ts` regenerated from `api/schemas.py` (hand-synced; single source of truth).
- Pages: Home (auth + sync health + worker count), workflow list page rendered from
  `GET /api/workflows` (today: Deviations) with inline edit, submit, status chips,
  filter/search, item detail (grouped by SF object), jobs (queue + logs), history
  (closed/skipped).
- Delete `Deck.tsx`, `DeviationsZ02.tsx`, `History.tsx` and rebuild them under the new
  model rather than porting. The deviations page is one instance of a shared
  `WorkflowPage` component driven by the workflow's catalogue and labels, so a second
  workflow needs no new screen.

**Gate:** `npm --prefix frontend run typecheck` and `npm run build` pass; the full
operator loop (log in → see rows → edit → submit → watch status) works in dev.

### Phase 9 — Cutover and cleanup (1 day)

- Switch `app/main.py` to the new stack and register the workflows explicitly; delete
  `store.py`, `browser.py`, `jobs.py`, `sync.py`, `routes.py`, `types.py`,
  `deviations/`, `deviations_z01..z04/`, `cancellations/`. `app/workflows/` contains only
  `deviations_z02/` at this point.
- Delete `data/app.db` (O-4) and any `sf_profile*` dirs left behind.
- Update `AGENTS.md` architecture section (new module map + workflow seam) and the
  "commands" block (`python -m app.browser --login` → new login module).
- Bump `__version__`, build the wheel, tag.

**Gate:** clean checkout → `python -m app.main` works with an empty data dir; login,
sync, extract, edit, submit, implement all reachable; `mypy`/`ruff`/`typecheck` clean;
`grep -r "deviations" app/core app/pipeline app/jobs app/salesforce` returns nothing.

---

## 4. Dependency graph

```
Phase 0 ─► Phase 1 ─► Phase 2 ─► Phase 3 ─┬─► Phase 4 ─► Phase 5 ─► Phase 7 ─► Phase 8 ─► Phase 9
                                          └─► Phase 6 ──────────────┘
                                          (O-1, O-2 gate Phase 6)
```

Phase 6 can start once Phase 3 lands (it needs adapters, not the queue). Phase 7 needs the
service façade only; it can be written against interfaces before Phase 6 is finished, but
must not ship before it.

---

## 5. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Async migration changes timing of Lightning page loads | swallowed rows, flaky extraction | `TabGroup` per-tab timeout + one retry; keep text-locator waits; validate with the smoke script before touching pipelines |
| Selectors drift | extraction silently returns 0 rows | header-total cross-check is mandatory in every run; skip-with-reason on empty detail; smoke script in CI-adjacent use |
| Session expiry mid-submit | half-applied writes | `AuthGate` pauses dispatch; `SUBMIT` phases are idempotent; per-field `applied` truth persisted before the next step |
| Two workers on one deviation | double implement | `jobs` partial unique index + lease + `transition()` asserting no terminal status under lease |
| Parallel tabs on one session trip SF limits | timeouts, `auraError` overlays | default 3 workers; per-tab timeout; open tabs only for the duration of one pipeline |
| SQLite contention with the loop | stalls under load | WAL + `busy_timeout`; single writer pattern (the loop thread) for job state; `to_thread` escape hatch documented |
| Frontend churn | beta UI regressions | rebuild views rather than port; ship behind the same Home page; typecheck gate |
| Over-abstraction (workflow seam built for workflows that never ship) | slower delivery, indirection nobody uses | seam is two protocols + one registry + a `workflow` column; no plugin loading, no dynamic discovery, no per-workflow tables. A fake workflow in tests proves the seam works, and if no second workflow lands the cost stays visible and small |
| Generic storage hides deviations' shape | harder queries, easier mistakes | `WorkItemRepository` is the only table reader and always takes an explicit `workflow`; workflow-specific access goes through `workflows/deviations_z02/` helpers |
| Refactor drifts from FRs | scope creep | every commit references an FR id; no feature outside the FR doc |

---

## 6. Definition of done

Mapped to the FR doc:

- FR-1: login from UI, snapshot persisted, expiry pauses and resumes the queue.
- FR-2: watcher samples every 30 s, single valid-sample rule, header warning surfaced,
  absent → terminal, `proposed` never clobbered.
- FR-3: all six objects extracted, parallel tabs, ambiguity → skip with reason.
- FR-4: one row per deviation, per-field extracted/last-synced/proposed/applied, catalogue
  extensible.
- FR-5: edits validated, one `SUBMIT` per deviation, no duplicates.
- FR-6: apply → validate → implement, no implement on failure or absence, idempotent,
  attribution recorded.
- FR-7: persisted queue, leases, warm browser, one worker-count knob, independent watcher,
  pause/cancel.
- FR-8: full audit trail; closed deviations queryable (per O-6).
- FR-9: plural-noun API, no legacy aliases, strict TS.
- Extensibility: `app/workflows/deviations_z02/` is the only place with deviation-specific
  code; a second workflow (fake, in tests) mounts through the same registry and router
  with no changes to `core/`, `salesforce/`, `pipeline/`, `jobs/`, or `api/`.
- NFR: `mypy --strict` + `basedpyright` + `ruff` clean, single browser process, per-deviation
  failure isolation, secrets never logged or returned.

---

## 7. Open items before Phase 1 / Phase 6

| ID | Needed by | Decision |
|---|---|---|
| O-1 field → object mapping | Phase 6 (and the catalogue in Phase 1) | which `FieldTarget`s |
| O-2 modal confirm label | Phase 6 | button text |
| O-3 z01–z04 / cancellations | Phase 1 | delete or keep |
| O-4 wipe `data/app.db` | Phase 1 | yes/no |
| O-6 archive vs hard delete | Phase 1 | affects `deviations` retention |

Only O-1 and O-4 actually stop work in Phase 1: the catalogue can ship with placeholder
targets, but the DB shape needs the wipe decision.

---

## 8. Live testing during the refactor

The v2 stack refuses the legacy `data/app.db` on purpose, so test against a separate data
directory until cutover (see O-4):

```bash
export SF_DATA_DIR="$PWD/data-v2"
.venv/bin/python -m app.salesforce.login        # once, headed browser
.venv/bin/python tools/smoke_list.py            # header == rows, valid=True
.venv/bin/python tools/smoke_extract.py         # first row
.venv/bin/python tools/smoke_extract.py Deviation-28102026-484106
```

- `smoke_list.py` prints the sampled header total, row count and validity.
- `smoke_extract.py` runs the real `DeviationsZ02Extraction` pipeline against the live org
  and prints the persisted fields, attributes and page refs plus the resulting status.
  Re-running re-extracts by default (`--no-force` respects `extracted_at`).

Extraction only reads Salesforce. Nothing is written to SF before Phase 6, so these runs
are safe. Both tools are dev-only and are not packaged in the wheel.
