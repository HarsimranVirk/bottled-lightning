# Functional Requirements — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v5.7 |
| **Date** | 2026-11-04 |
| **Scope** | Loan deviations workflow only |
| **Supersedes** | The pre-refactor behaviour in `app/deviations*`, `app/sync.py`, `app/jobs.py` |

---

## 1. Purpose

Automate the extraction, review and update of loan deviations from Salesforce, and present every object involved in a deviation in one place, so a single operator can:

1. see every deviation currently queued in SF,
2. see the linked objects and their values without opening five record pages by hand,
3. change the values that need changing,
4. have those changes written back to SF, verified, and the deviation implemented —
   without ever implementing a deviation whose values did not save correctly.

## 2. Scope

### In scope

- Manual authentication and session persistence.
- Continuous synchronisation with the loan-deviation list view.
- Per-deviation extraction across the deviation record, Opportunity, CL contract,
  collateral, LMS 2.0 CL contract and LMS 2.0 collateral.
- A unified per-deviation view with editable values.
- Submission: write values → verify → implement the deviation.
- A persistent job queue and always-alive SF browser workers.
- Audit of extraction, edits, applies, validations and closures.

### Out of scope

- Cancellations and any other workflow (`app/cancellations/`).
- REST/Data Loader automation of SF (session is host-locked; UI automation only).
- Multiple operators, roles, permissions or concurrent human editors.
- Bulk submission across several deviations in one action.
- Editing any field beyond the editable-value catalogue defined in FR-4.3.
- Analytics/reporting beyond the audit trail in FR-8.

## 3. Actors

- **Operator** — the single human user. Performs the manual SF login, reviews the
  unified view, edits values, submits deviations, and resolves rows flagged
  `needs_review`.
- **System** — synchronises the list, extracts, applies, validates, implements, and
  records everything it did.

## 4. Definitions

- **Deviation** — a `Consumer_Loan_Deviation__c` record (key prefix `a2f`) shown in the
  list view `Z2_Loan_para_pricing1` (`fcf=00BNo000006HMof`). Identified by its
  `Deviation-…` number.
- **Page ref** — a typed link (kind + name + URL) to an object related to a deviation:
  `opportunity`, `cl_contract`, `collateral`, `lms2_cl_contract`, `lms2_collateral`.
- **Phase** — an ordered step of a `SUBMIT` job: *apply*, *validate*, *implement*.
- **Editable value** — one of the fields listed in FR-4.3.
- **Terminal status** — a status that removes the deviation from the active work
  (`implemented`, `closed`, `skipped`).
- **Presence epoch** — one continuous period during which a deviation is present in the
  SF list. A deviation that disappears and later reappears begins a new epoch.
- **Session snapshot** — the Playwright `storage_state()` captured after a manual login
  and injected into every browser launch.
- **Review decision** — the operator's accept/reject judgement on a deviation, recorded
  locally before submission. It is not a Salesforce write and is reversible.

---

## 5. Functional requirements

### FR-1 Authentication & session

- **FR-1.1** Authentication is manual and triggered from the UI. The system opens a
  browser for the operator to log in. No password is stored and no API-based login is
  attempted.
- **FR-1.2** Immediately after a successful manual login the system snapshots the
  browser state and persists it in SQLite (`sessions`). That snapshot is the
  authoritative session store.
- **FR-1.3** Every browser launched by the system injects the saved snapshot before
  navigating, so application restarts do not require re-login.
- **FR-1.4** Session expiry is detected on any SF interaction. On expiry the system:
  stops dispatching new jobs; marks queued and in-flight work as blocked-on-auth rather
  than failed; surfaces a clear "manual login required" state in the UI; and resumes or
  requeues that work automatically once a fresh snapshot exists.
- **FR-1.5** The operator can see the last login/expiry state and can clear the stored
  session to force a fresh login.

### FR-2 Deviation list sync

- **FR-2.1** The system keeps one long-lived SF Lightning page on the loan-deviation list
  view in a dedicated tab that never runs jobs.
- **FR-2.2** That page is refreshed every 30 seconds (configurable) and the live rows are
  read from it.
- **FR-2.3** Each refresh reconciles the stored data against SF: newly appearing
  deviations are added, list-visible values of known deviations are updated, and missing
  deviations are closed (FR-2.6). The approval date is such a value: SF fills it after a
  deviation first appears, so a later sync must add it (and must never clear a known
  date when a sample omits it).
- **FR-2.4** The "N items" header total is read on every refresh and compared with the
  number of rows parsed. A mismatch makes the refresh invalid (FR-2.9); it is persisted
  and shown as a sync warning and is never silently ignored.
- **FR-2.5** A refresh never overwrites values the operator has edited but not yet
  submitted. The synced value is retained separately as `last_synced`; the operator's
  value takes precedence until submission.
- **FR-2.6** A deviation absent from a **valid** refresh is considered closed in SF
  (implemented or cancelled elsewhere). It is removed from the active queue: no further
  jobs are created for it, it leaves the working view, and any queued work for it is
  dropped.
- **FR-2.7** If a deviation disappears while a job is running, that job aborts at the
  next safe boundary and must never reach the implement step. Any writes already made
  are recorded but not retried.
- **FR-2.8** Closure is attributed from the system's own record of actions: if the
  implement click was made and confirmed, the closure is recorded as `implemented` with
  `source=system`; if no implement was attempted, it is recorded as `closed` with
  `source=external`. If the click was made but its outcome was never confirmed, it is
  recorded as `implemented` with `source=system` and an `implement_unconfirmed` flag for
  review.
- **FR-2.9** A refresh is valid only when the page loaded, the "N items" header total was
  parsed, and the number of rows parsed equals that total. An invalid refresh changes no
  state. Closure is applied on the first valid refresh that reports a deviation absent —
  there is no multi-sample rule.

### FR-3 Extraction

- **FR-3.1** Extraction runs per deviation as an `EXTRACT` job, never as one monolithic
  batch job.
- **FR-3.2** From the deviation record page the system captures: cleaned description,
  `requested_roi`, `ideal_roi`, `updated_roi`, `requested_variance`, record id, record
  URL and the Opportunity link.
- **FR-3.3** From the description the system parses `property_value`, `loan_amount`,
  `tenure` and `emi_incl_hffc`. The bare `EMI-` pre-calculated line must never be
  captured; only the `EMIs & other …` line is. Parsing is best-effort: a value the parser
  cannot find is left empty, which is neither a failure nor a skip — the operator can
  supply it in the unified view.
- **FR-3.4** From the Opportunity page the system captures the product type and maps it
  to the CL-contract product using the existing product mapping.
- **FR-3.5** The system discovers and records page refs for the Opportunity, the matching
  CL contract, the collateral, the LMS 2.0 CL contract and the LMS 2.0 collateral.
  The LMS 2.0 CL contract is narrowed by the *same* product mapping as the CL contract,
  because a loan legitimately has more than one LMS 2.0 CL contract.
- **FR-3.6** All pages belonging to one deviation are opened in parallel tabs within the
  same authenticated session. The deviation is complete only when every page has been
  read or explicitly skipped.
- **FR-3.7** Ambiguity is a skip, never a guess. Ambiguous means several candidates that
  match the *required* product (for CL contracts and LMS 2.0 CL contracts), several
  collaterals, a missing detail page, or an SF internal error — each records the deviation
  as skipped with a human-readable reason.
- **FR-3.8** Linked-object pages are cached and are not re-scraped on every sync.
  Re-extraction happens only for newly seen deviations, or on an explicit operator
  refresh.

### FR-4 Unified view

- **FR-4.1** The system presents one row per deviation, collating fields from the
  deviation record, Opportunity, CL contract, collateral, LMS 2.0 CL contract and LMS
  2.0 collateral, plus the deviation's status.
- **FR-4.2** For each editable value the view distinguishes: extracted value,
  last-synced value, operator's proposed value, applied value, and per-field status.
- **FR-4.3** The editable values in v1 are `loan_amount`, `property_value`, `tenure` and
  `emi_incl_hffc`. The set must be extensible by adding catalogue entries, without
  changes to adapters or the API shape.
- **FR-4.4** All other extracted fields (the ROI family, requested variance, product
  type, page refs) are read-only.
- **FR-4.5** Rows carry a status that shows exactly where the deviation is in the
  pipeline. Failed rows state which step and which object failed, with the reason.
- **FR-4.6** The view is filterable by status and searchable. Closed deviations leave
  the working view but remain accessible in history (see FR-8.2).
- **FR-4.7** The unified view opens as a **review deck**: one deviation per card, for a
  fast accept/reject decision (FR-10). A *History* toggle shows every deviation the deck
  approved; the general list/search view is not part of the operator flow.

### FR-5 Editing

- **FR-5.1** The operator can edit one or more editable values on a deviation and submit
  that deviation for update.
- **FR-5.2** Edits are validated before acceptance: required fields present, and
  per-field numeric/format rules honoured.
- **FR-5.3** A submission is persisted: which fields, previous value, new value and
  timestamp.
- **FR-5.4** Submitting enqueues exactly one `SUBMIT` job per deviation. Re-submitting
  while a submit is queued or running is refused or coalesced — never duplicated.
- **FR-5.5** The operator can discard pending edits and revert to the extracted or
  last-synced value.

### FR-6 Submission: apply → validate → implement

- **FR-6.1** A `SUBMIT` job runs three ordered phases for exactly one deviation:
  **apply** (write the values), **validate** (the writes landed), **implement** (final
  SF operation).
- **FR-6.2** Before writing, the job re-reads the current SF values. If they differ from
  the values the edit was based on, the job aborts and flags the deviation for review
  instead of overwriting someone else's change. Presence is checked twice: at the start
  of apply, where an absent deviation skips all writes, and again as the last validation
  step immediately before implementing (FR-6.5).
- **FR-6.3** Apply writes each editable value to its configured target object(s). Where
  a value must exist consistently on more than one object, all targets are written and
  all must agree.
- **FR-6.4** Validation means: every written value was accepted by SF and reads back
  equal to the intended value, **and** the deviation is still present in the list view.
  A write that does not stick is a failure. An absent deviation is not a failure — it
  means SF already closed it (see FR-6.6).
- **FR-6.5** `Implement` is clicked only when apply succeeded, every value read back
  equal, and the deviation is still present. If the deviation is absent at the validation
  check, the implement step is skipped entirely: no modal is opened and nothing is
  confirmed.
- **FR-6.6** Any failure before the final action aborts the job, so a deviation is never
  implemented on partial or unverified success. An absence-driven skip is a clean
  terminal outcome, not an error: the deviation is recorded as `closed` with
  `source=external` and reason `already_implemented`, the job is marked successful, and
  it is neither retried nor sent to review.
- **FR-6.7** Implement success is confirmed immediately after the confirm action by the
  deviation page state (the button/status changes). It is not inferred from a toast
  string, and not from list absence. If that observation cannot be made, FR-6.12 applies.
- **FR-6.8** `SUBMIT` is idempotent with respect to its effects: retrying after a crash
  must not double-write or double-implement. Per-phase and per-object progress is
  persisted before and after every action.
- **FR-6.9** A failed `SUBMIT` leaves the deviation recoverable, with per-field truth of
  what was and was not applied, and retryable once the cause is fixed.
- **FR-6.10** Only the `SUBMIT` pipeline writes terminal status. The list watcher writes
  observations only (`last_seen_at`, `absent_since`, header total).
- **FR-6.11** Closure is applied on the first valid refresh reporting absence, except
  while a `SUBMIT` lease is held: then `absent_pending` is recorded and the close is
  applied when the lease is released. Work is never yanked out from under a running job.
- **FR-6.12** There is no record-page reconciliation. If the implement click was made but
  its outcome was never confirmed (page died, timeout), the closure is attributed
  `source=system` and carries an `implement_unconfirmed` flag for operator review.
- **FR-6.13** A deviation that reappears after being closed starts a new presence epoch
  and returns to `present`, with its prior history intact.

### FR-7 Jobs & workers

- **FR-7.1** There is a single queue of typed, persisted jobs: `EXTRACT(deviation)` and
  `SUBMIT(deviation)`, plus internal refresh work. Each job carries subject, status,
  attempts, lease, timestamps and log lines.
- **FR-7.2** Jobs are claimed with a lease, so a restart or a crashed worker can neither
  lose nor double-run them. Stale leases are requeued.
- **FR-7.3** Workers are always-alive: the browser is launched once and kept warm for the
  lifetime of the process. Tabs are opened per job and closed when the job ends.
- **FR-7.4** Concurrency is controlled by a single worker-count setting (default 3,
  maximum 5). One worker handles one deviation at a time and opens that deviation's tabs
  in parallel.
- **FR-7.5** The list-watching tab is separate from the job workers and never consumes a
  worker slot.
- **FR-7.6** Every job produces a readable log (per phase, per object, per tab) that is
  visible in the UI and retained.
- **FR-7.7** Operator controls: view the queue and per-job progress, pause and resume
  dispatch, and cancel queued jobs. Running SF work is never force-killed mid-write.
- **FR-7.8** Dispatch pauses automatically on session expiry and resumes after re-login.
- **FR-7.9** Every job exposes the time it took: the interval from `started_at` to
  `finished_at` for terminal jobs, and the live elapsed time for a running job. A job
  that never started shows no duration. Duration is derived from the stored timestamps,
  so it survives restarts without a second source of truth.
- **FR-7.10** The jobs screen is a standard data table: server-side pagination with a
  total count and page size, column sorting, and a filter for every displayed column
  (id, status, kind, phase, item, started date range, duration range, error) placed
  directly in a second header row under the column label. Filters compose, the count
  reflects the filtered set, and changing a filter or sort returns to the first page.

### FR-8 History & audit

- **FR-8.1** For each deviation the system retains: extracted values, every operator edit
  (old value → new value, timestamp, submission), applied values, validation result,
  implement result, and every skip or failure reason.
- **FR-8.2** Closed deviations leave the queue and the working view but are retained in a
  read-only record (values, status, attribution, reason, page refs) for later lookup.
  *Pending decision O-6: retain as archive, or hard-delete.*
- **FR-8.3** The previous archive-then-delete behaviour is superseded by status plus
  retained history.

### FR-9 API & frontend

- **FR-9.1** The REST surface follows the project convention: plural nouns, no verb
  segments, selection by path parameter, filters and pagination in query parameters.
- **FR-9.2** The API exposes: session status/create/delete, sync status and manual
  trigger, the unified view (list and single deviation), field-value edits, submission
  as a job sub-resource, jobs and job logs, worker/queue status, and update status.
- **FR-9.3** The frontend shows: authentication state with the manual-login trigger, sync
  health including header-count mismatch, the review deck, the unified view with inline
  editing and submission, per-deviation detail grouped by SF object, a live job/queue
  strip, and a footer carrying the running app version and quiet session/sync status.
  A healthy session does not show a persistent banner; banners are reserved for problems.
- **FR-9.4** The frontend is TypeScript strict, shared payload types live in one place,
  and `any` is not used.
- **FR-9.5** Every screen implements an explicit state matrix: loading, empty, ready,
  invalid-sync, paused, and each terminal status. No screen may be designed only for the
  happy path.
- **FR-9.6** The server is the only source of truth for status. The UI never derives an
  item's status from its own actions and never applies an optimistic status change.
- **FR-9.7** Editable values are validated by the server. A `422` is shown against the
  specific field, the other drafts are preserved, and the item stays editable.
- **FR-9.8** Background polling stops while the document is hidden and resumes when it is
  visible; it never overwrites an in-progress edit. A failed request must not stop later
  polls: the next interval retries, so a restarted backend recovers without a reload. An
  untrusted-refresh warning always shows the age of the failed check, so a stale banner
  cannot be mistaken for a live failure.
- **FR-9.9** Submitting a declaration requires an explicit confirmation naming the item
  and the changed values; the button is disabled unless the item is submittable.
- **FR-9.10** The full edit → save → submit path is keyboard-reachable, the detail panel
  traps focus while open, and status changes are announced to assistive technology.
- **FR-9.11** `frontend/src/types.ts` is generated from the OpenAPI schema; a contract
  change that is not regenerated fails the typecheck.
- **FR-9.12** UI changes ship with screenshots of their state-matrix rows at narrow,
  medium and wide widths.
- **FR-9.13** No screen requires horizontal scrolling at 390, 768 or 1280 px. Tables hide
  columns and the filters sit in the column headers instead of widening the page. All
  data text (the deck description, ROI values, page refs and detail fields) is selectable
  so the operator can copy values. The deck has no drag gesture (FR-10.9).
- **FR-9.14** The UI is built from Salt DS components only: Tabs for navigation,
  ToggleButtonGroup for view switches, Table for tables, FormField/Input/Dropdown for
  filters, Card/Panel for surfaces, Banner for messages, StatusIndicator for status, and
  Button for actions. CSS is limited to layout (widths, padding, responsive column
  hiding, motion); no bespoke control look may be introduced.

### FR-10 Review decisions (accept / reject)

- **FR-10.1** Every deviation awaiting a decision is presented one card at a time. The
  operator accepts it (the values are right, it should be implemented) or rejects it
  (it should not be implemented as-is).
- **FR-10.2** Accept records an `accepted` decision and first stores the card's corrected
  field values as proposals. Reject records a `rejected` decision with an optional reason
  and no values. Neither writes to Salesforce; the proposals are local edits awaiting the
  submitter.
- **FR-10.3** Decisions are reversible. Undoing a decision returns the item to undecided
  and it re-enters the deck.
- **FR-10.4** A decided item leaves the deck immediately and stays out of it until it is
  undone. Decided items remain visible in the list and detail view with their decision.
- **FR-10.5** The deck shows only items in a decidable status (`ready`, `editing`,
  `needs_review`). Terminal and in-flight items never appear.
- **FR-10.6** Accepted items are the submission queue. When FR-6 exists, acceptance hands
  the item to the submitter; acceptance alone never submits, never implies SF success,
  and never marks the item terminal.
- **FR-10.7** Rejection is not a skip. It does not alter extraction state or the pipeline
  status, and the item keeps syncing from Salesforce.
- **FR-10.8** Every decision is audited with its kind, reason and timestamp, and is shown
  in the item detail history.
- **FR-10.9** Decisions are made with two explicit buttons, **Skip** and **Accept**, that
  span the card width. There are no swipe or arrow-key shortcuts: an accidental gesture
  must never be able to accept a deviation. The buttons are keyboard reachable through
  the normal tab order, and the result is announced through `aria-live`.
- **FR-10.10** The card shows every editable value, prefilled from the extracted value,
  so missing or unparsed values are visible and correctable before a decision. A missing
  value is a warning on the card, not a block: the single operator decides whether the
  deviation is decidable. Accept persists the card's values as proposals (FR-10.2).
- **FR-10.11** Decisions never gate sync or extraction. An accepted or rejected item is
  still reconciled with the list view like any other.

---

## 6. Non-functional requirements

- **NFR-1 Typing and lint** — the Python codebase stays fully typed: no `Any`, no
  `cast`/`# type: ignore` escapes without written justification, no bare `dict`/`list`.
  `mypy --strict` and `basedpyright` are clean, `ruff` is clean, and the frontend passes
  TypeScript `strict`.
- **NFR-2 Memory and compute** — exactly one browser process for the application.
  Concurrent tabs are bounded by worker count × pages per deviation, and tabs are closed
  promptly when a job ends. The system must remain usable at default settings on a
  typical developer laptop.
- **NFR-3 Resilience** — failure of any single deviation never stalls the queue; the
  queue always drains and reports.
- **NFR-4 Observability** — every SF decision (skip, abort, retry, implement, closure)
  leaves a log line carrying deviation id, phase and reason.
- **NFR-5 Security** — the SF session snapshot is as sensitive as the account password.
  It is never committed, never logged, and never returned by any API response.
- **NFR-6 Packaging** — releases stay wheel-based; self-update guards (version and
  sha256 verification, never update mid-job) are preserved; installed builds keep state
  in the OS app-data directory.
- **NFR-7 Sync budget** — a refresh cycle completes well within its 30-second interval
  while up to the configured number of extraction jobs run concurrently.

---

## Appendix A — Status vocabulary

Working states: `present`, `extracting`, `ready`, `editing`, `submitting`,
`applying`, `validating`, `implementing`, `absent_pending`, `needs_review`.

Terminal states:

- `implemented` — closed by this system's implement action. Always `source=system`;
  may carry the `implement_unconfirmed` flag when the confirm click's outcome was never
  observed.
- `closed` — left the list without this system implementing it. `source=external`, with
  a reason such as `already_implemented` or `cancelled`.
- `skipped` — extraction could not proceed (ambiguity or SF error), with reason.

`absent_pending` is the only non-terminal closure marker: a valid refresh reported
absence while a `SUBMIT` lease was held.

## Appendix B — Open items

| ID | Question | Blocks |
|---|---|---|
| O-1 | Which SF object and field label each of `loan_amount`, `property_value`, `tenure`, `emi_incl_hffc` is written to, and whether any value fans out to several objects. | FR-6.3, data model |
| O-2 | Exact label of the modal confirm button for `Implement`. | FR-6.5 |
| O-3 | Whether `z01`/`z03`/`z04` and `app/cancellations/` are live or dead scaffolding (proposed: delete). | Architecture |
| O-4 | ~~Wipe the legacy `data/app.db` for the new schema.~~ **Resolved** — wiped; `data/` now holds the workflow store. | — |
| O-5 | ~~Whether the deviation record page remains readable after implement.~~ **Resolved** — no record-page reconciliation; attribution is local (FR-6.12). | — |
| O-6 | Archive or hard-delete closed deviations (FR-8.2). | FR-8.2, data model |
| O-7 | Should accepted items auto-submit once Phase 6 lands, or wait for an explicit
  submit action? (Default: explicit action; acceptance only queues.) | FR-10.6 |

## Appendix C — Change log

- **v5.7** — the List view is replaced by an accepted-deviations **History** table
  (paginated, newest decision first); jobs filters moved into the column headers; every
  control and surface is a Salt DS component (FR-9.14).

- **v5.6** — jobs table: duration per job (derived from started/finished, live for a
  running job), server-side pagination with a total, sortable columns, and filters for
  every column. `GET /api/jobs` returns `{count, total, rows}` and `JobView.durationMs`.

- **v5.5** — the always-on healthy banner is gone: session/sync status moves to a footer
  that also shows the running app version (`GET /api/version`). Only problems (expired
  session, untrusted refresh) raise a banner.

- **v5.4** — decision gestures are removed: Skip/Accept are the only paths and they span
  the card width. The card shows the SF approval date (dash when SF has none), the
  deviation number is an absolute Salesforce record link, and the separate *Details*
  button is gone because the card already carries everything.

- **v5.3** — responsive requirement (FR-9.13): no horizontal page scrolling at any
  review width, and all data text stays selectable; the deck omits its drag on the
  description/ROI/ref panels so values can be copied.

- **v5.2** — the review deck is restored to the legacy card shape: record link, approval
  date, pages to update, raw description, ROI details, four editable prefilled parameters,
  accepted/skipped/to-review tallies, next-up and *Replay skipped*. Accept stores the
  card's corrected values as proposals before recording the decision; skip stores no
  values.

- **v5.1** — the sync banner no longer sticks: polling retries after a failed request
(a server restart used to freeze the last snapshot), and an untrusted refresh states how
old it is. The list page waits for the "N items" header before its first sample, so a
process start no longer records a spurious invalid refresh.

- **v5** — review deck (FR-10): local, reversible accept/reject decisions recorded
  before submission; the deck is the default view of the unified page. Decisions do not
  write to SF, do not change pipeline status, and are the submission queue once FR-6
  exists.

- **v2.1** — single-valid-refresh closure (header total must equal parsed rows; no
  two-sample rule); closure attributed locally from recorded actions; validation includes
  presence, so an already-closed deviation skips the implement step as a clean terminal
  outcome (`closed` / `already_implemented`); `closure_unknown` and the record-page
  reconcile job removed in favour of an `implement_unconfirmed` flag.
- **v2** — phase-per-deviation jobs (`EXTRACT`, `SUBMIT`); async single-browser runtime
  with a warm tab pool; live list refresh that never clobbers pending edits; closure
  semantics split into absence (removal) and page state (success); attribution with
  `closure_unknown` reconciliation; single `DEVIATION_WORKERS` concurrency setting.
