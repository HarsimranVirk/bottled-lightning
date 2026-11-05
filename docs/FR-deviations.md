# Functional Requirements — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v5.24 |
| **Date** | 2026-11-05 |
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
  `tenure` and `emi_incl_hffc`. When the description contains both Old and New parameter
  blocks, prefill a field only when the New value differs from the Old value; an equal
  value is left empty because no update is needed. A field present only in the New block
  is prefilled; a field present only in the Old block, or a description with no Old/New
  structure, is left empty because there is not enough confidence that it changed. Only
  the **New** block is authoritative; old values are never written. If the New block
  omits a field, that field stays empty rather than inheriting the old value. The bare
  `EMI-` pre-calculated line must never be captured; only the `EMIs & other …` line is.
  Parsing is best-effort and conservative: a value the parser cannot confidently
  identify as changed is left empty, which is neither a failure nor a skip — the operator
  can supply it. The parser writes the raw New text and does not guess units; the
  operator handles the details.
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
- **FR-5.6** Only non-empty proposed values are written. An empty or whitespace-only
  value means “no update” and is never sent to Salesforce; the API treats it as
  discarding the proposal. Submitting with no non-empty proposals is rejected.

### FR-6 Submission: apply → validate → implement

- **FR-6.1** A `SUBMIT` job runs three ordered phases for exactly one deviation:
  **apply** (write the values), **validate** (the writes landed), **implement** (final
  SF operation).
- **FR-6.2** Before writing, the job re-reads the current SF values and records them for
  the audit and for idempotency (a target already holding the intended value is not
  written again). A difference from the last watcher snapshot does **not** block the
  write: description-derived values are not guaranteed to be true, so the operator's
  proposed value is authoritative. Presence is still checked twice: at the start of
  apply, where an absent deviation skips all writes, and again as the last validation
  step immediately before implementing (FR-6.5).
- **FR-6.3** Apply writes each editable value to its configured target object(s). Where
  a value must exist consistently on more than one object, all targets are written and
  all must agree.
- **FR-6.4** Validation means: every written value was accepted by SF and reads back
  equal to the intended value, **and** the deviation is still present in the list view.
  A write that does not stick is a failure. An absent deviation is not a failure — it
  means SF already closed it (see FR-6.6).
- **FR-6.5** `Implement` is clicked only when apply succeeded, every value read back
  equal, and the deviation is still present. The action runs on the deviation record page,
  opened from the item's record URL. If the deviation's Implemented checkbox is already
  ticked, no click happens and the run returns `already_closed` (FR-6.16). If the
  deviation is absent at the validation check, the implement step is skipped entirely.
- **FR-6.6** Any failure before the final action aborts the job, so a deviation is never
  implemented on partial or unverified success. An absence-driven skip is a clean
  terminal outcome, not an error: the deviation is recorded as `closed` with
  `source=external` and reason `already_implemented`, the job is marked successful, and
  it is neither retried nor sent to review.
- **FR-6.7** Implement success is confirmed immediately after the click by the deviation's
  Implemented checkbox turning ticked. It is not inferred from a toast string, and not
  from list absence. If the tick cannot be observed within the request timeout, the run
  fails to `needs_review` and `execute_attempted_at` stays set (FR-6.12).
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
  If a first close attempt cannot complete, the next valid refresh retries it; a
  non-terminal item is never left in the working queue just because it is already marked
  absent.
- **FR-6.12** There is no record-page reconciliation. If the implement click was made but
  its outcome was never confirmed (page died, timeout), the closure is attributed
  `source=system` and carries an `implement_unconfirmed` flag for operator review.
- **FR-6.13** A deviation that reappears after being closed starts a new presence epoch
  and returns to `present`, with its prior history intact.
- **FR-6.14** The validate-only bring-up mode is retired: the submission pipeline always
  performs the final action. There is no configuration switch that skips it. A deployment
  that must not implement deviations should not submit them.
- **FR-6.15** A failed submit does not roll back values that were already written. It
  records per-target truth (`applied` / `rejected`), moves the deviation to
  `needs_review`, fails the job, and notifies the operator with the field/object that
  failed. The operator fixes the cause and resubmits.
- **FR-6.16** A deviation whose Implemented checkbox is already ticked before the click is
  not implemented again and is not attributed to us: the run returns `already_closed`, and
  the first valid refresh that no longer shows the deviation records `closed` with
  `source=external` and reason `already_implemented`. No execute timestamps are written.

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
- **FR-7.11** Jobs filters follow the standard table-filter pattern (FR-9.18). Status,
  kind and phase are multiselect checkbox lists; id, item and error combine a contains
  text input with exact-value checkboxes. Repeated values are sent to the server so the
  filtered total and every page are correct. Started and duration keep their range
  inputs (FR-9.19).

### FR-8 History & audit

- **FR-8.1** For each deviation the system retains: extracted values, every operator edit
  (old value → new value, timestamp, submission), applied values, validation result,
  implement result, and every skip or failure reason.
- **FR-8.2** Closed deviations leave the queue and the working view but are retained in a
  read-only record (values, status, attribution, reason, page refs) for later lookup.
  Accepted deviations are retained in the segregated snapshot store; non-accepted
  current items are removed by the 24-hour current purge (FR-11.1).
- **FR-8.3** The previous archive-then-delete behaviour is superseded by status plus
  retained history.
- **FR-8.4** Accepted deviations are copied into a separate approved-history store when
  the accept decision is recorded. The snapshot contains the item identity, status at
  snapshot time, SF approval date, reason, record URL, accepted decision, fields,
  attributes, page refs and edit audit. The snapshot is refreshed when a submit starts,
  when a submit job finishes, and when a closure resolves; undo or reject removes it.
- **FR-8.5** The History tab and its detail drawer read only the approved-history store,
  never `work_items` or `item_decisions`. A history row therefore remains readable after
  its current work item is purged.
- **FR-8.6** Current work items and approved history have independent retention windows.
  The current work-item purge keeps the last 24 hours and also removes the terminal jobs
  and job logs of every item it deletes; the approved-history purge keeps the last 3
  months (90 days). Neither purge may erase the other store.
- **FR-8.7** Both purges are manual. They are triggered from the hidden `/dev/db` page,
  are localhost-only, and require an explicit confirmation with the cutoff and the
  per-table counts shown before the destructive action. The single automatic deletion in
  the system is the bounded `sync_runs` ring in FR-8.9; it removes nothing an operator can
  read.
- **FR-8.8** History uses the same standard table-filter pattern as every other table:
  deviation key, status, SF approval and each displayed value column have a text input
  and exact-value checkboxes; the decided date uses the range variant. The filtered total
  and pagination come from the server.
- **FR-8.9** Each workflow retains its 20 newest `sync_runs` rows; older rows are deleted
  automatically in the same transaction that records a new sample. The newest row is never
  deleted, so the sync banner always has a reading. The retained window matches the
  documented `recent(limit=20)` read; `latest()` is the only production reader.
- **FR-8.10** The current purge also deletes `jobs` and `job_logs` belonging to the items
  it removes. Only terminal jobs (`succeeded`, `failed`, `cancelled`) may be deleted;
  `queued`, `running` and `blocked_auth` rows always survive. A job whose item is not
  purged is retained even when it is old. Consequently the Jobs page keeps history only
  for items inside the current store, i.e. until the next current purge past their 24-hour
  window.
- **FR-8.11** Every approved-history row exposes the item's five object links —
  opportunity, CL contract, collateral, LMS2 CL contract and LMS2 collateral — as five
  table columns. Each cell shows the linked object's `name` and opens its Salesforce URL in
  a new tab; a kind with no stored ref shows `—` and is not clickable. The links come from
  the snapshot's refs, so they remain readable after the current work item is purged.

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
- **FR-9.9** In the current phase Accept is the submission action and does not open a
  separate confirmation dialog; its label is “Accept & update” and the card's values are
  visible before it is pressed. The button is disabled unless the item is submittable. A
  dedicated confirmation is deliberately not shown now that the final action runs:
  submissions must stay fast.
- **FR-9.10** The full edit → save → submit path is keyboard-reachable, the detail panel
  traps focus while open, and status changes are announced to assistive technology.
- **FR-9.11** `frontend/src/types.ts` is generated from the OpenAPI schema; a contract
  change that is not regenerated fails the typecheck.
- **FR-9.12** UI changes ship with screenshots of their state-matrix rows at narrow,
  medium and wide widths.
- **FR-9.13** No screen scrolls horizontally at its default layout at 390, 768 or 1280 px.
  A table whose columns the operator widens — and the History table with its full column
  set at 1280 px — scrolls inside its own container instead of widening the page. Tables
  hide columns and the filters sit in the column headers instead of widening the page. All
  data text (the deck description, ROI values, page refs and detail fields) is selectable
  so the operator can copy values. The deck has no drag gesture (FR-10.9).
- **FR-9.14** The UI is built from Salt DS components only: Tabs for navigation,
  ToggleButtonGroup for view switches, Table for tables, FormField/Input/Dropdown for
  filters, Card/Panel for surfaces, Banner for messages, StatusIndicator for status, and
  Button for actions. CSS is limited to layout (widths, padding, responsive column
  hiding, motion); no bespoke control look may be introduced.
- **FR-9.15** The header has a light/dark theme toggle. A first visit follows the OS
  `prefers-color-scheme`; after the operator toggles, the explicit choice is persisted in
  `localStorage` and wins on later visits. The theme is client-only and changes no backend
  state. The control is keyboard reachable and its accessible name describes the action
  (“Switch to dark mode” / “Switch to light mode”).
- **FR-9.16** Refresh controls pair the refresh icon with a one- or two-word context:
  **Sync now** for an immediate watcher refresh, **Retry sync** in the untrusted-refresh
  banner, and **Reload deck** for a frontend list refetch. A bare “Refresh” button is not
  used.
- **FR-9.17** The History view is a separate route from the deck (`?view=history`), and
  opening a history row uses the history detail endpoint. The history detail is read-only
  and never offers an Undo decision action.
- **FR-9.18** Every data table uses one shared table-filter pattern: a text input and a
  multiselect dropdown with checkboxes for exact values. An empty selection means all
  values; selected values are OR within one column, columns compose with AND, and the
  text plus the selected values in the same column also compose with AND. The trigger
  shows “All” or “N selected”. Date and duration ranges use the shared range variant
  (two inputs) instead of a checkbox list.
- **FR-9.19** The Dev DB results table applies the standard filter to every column,
  using the distinct non-empty values in the current preview as checkbox options. This
  filtering remains client-side over the bounded preview; exports still run the full SQL.
  Future tables must reuse the shared filter components rather than adding bespoke
  filter cells.
- **FR-9.20** Every real table (History, Jobs, Dev DB results) is paginated. History and
  Jobs page on the server with a filtered total; the Dev DB preview pages on the client
  over its capped result, because arbitrary read-only SQL has no stable cursor.
- **FR-9.21** Every column of every real table is filterable using FR-9.18. Object-link
  columns filter on the linked object's name with the same text + multiselect pair; the
  server receives every selected value so totals and later pages stay correct.
- **FR-9.22** Every column of every real table is resizable. Widths persist per table
  across reloads, a Reset action restores the defaults, and resizing is keyboard-operable
  from the header. Resizing is unavailable below 900 px, where columns are hidden by
  breakpoint instead.
- **FR-9.23** A table that does not fit its container scrolls horizontally inside the
  table container only; the page itself never scrolls sideways. Default widths must fit at
  390, 768 and 1280 px, except History's full column set at 1280 px (FR-9.13).
- **FR-9.24** The three real tables share one implementation — a single `DataTable`
  component built from Salt DS primitives — so pagination, filters, widths and scrolling
  cannot diverge between screens. Bespoke table markup is not allowed.

### FR-10 Review decisions (accept / reject)

- **FR-10.1** Every deviation awaiting a decision is presented one card at a time. The
  operator accepts it (the values are right, it should be implemented) or rejects it
  (it should not be implemented as-is).
- **FR-10.2** Accept records an `accepted` decision and stores the card's corrected field
  values. If at least one value is non-empty, it also enqueues exactly one `SUBMIT` job.
  A card with no values records the decision only. Reject records a `rejected` decision
  with an optional reason and no values; it never writes to Salesforce. The submit job
  writes, validates and implements the accepted values (FR-6.5).
- **FR-10.3** Decisions are reversible. Undoing a decision returns the item to undecided
  and it re-enters the deck.
- **FR-10.4** A decided item leaves the deck immediately, except an accepted item that
  comes back in `needs_review` after a failed submit. That card stays in the deck with its
  failure reason until it is corrected and accepted again or its decision is undone.
  Decided items remain visible in the list and detail view with their decision.
- **FR-10.5** The deck shows only items in a decidable status (`ready`, `editing`,
  `needs_review`). Terminal and in-flight items never appear.
- **FR-10.6** Accepted items with non-empty values are the submission queue: acceptance
  enqueues the `SUBMIT` job immediately. Acceptance with no values is a local decision
  only. Acceptance never implies Implement success; a confirmed run leaves the item in
  `executing` until the next valid refresh completes the closure, and a failed run returns
  it to `needs_review`.
- **FR-10.7** Rejection is not a skip. It does not alter extraction state or the pipeline
  status, and the item keeps syncing from Salesforce.
- **FR-10.8** Every decision is audited with its kind, reason and timestamp, and is shown
  in the item detail history.
- **FR-10.9** Decisions are made with two explicit buttons, **Skip** and **Accept &
  update**, that span the card width. The buttons carry the shortcut in their labels
  (`Skip (Shift+←)`, `Accept & update (Shift+→)`) and expose it through
  `aria-keyshortcuts`. `Shift+←` records a skip and `Shift+→` runs the same
  accept-and-submit flow as the button: only while a decidable card is on screen and no
  decision is in flight, and never while a text field or an open dialog owns the
  keystroke, with another modifier held, or on key auto-repeat. `Shift+→` may enqueue a
  Salesforce write when the card has values; there is no confirmation dialog in the
  current phase. There is no drag or swipe gesture. The buttons remain keyboard reachable
  through the normal tab order, and the result is announced through `aria-live`.
- **FR-10.10** The card shows every editable value, prefilled from the extracted value,
  so missing or unparsed values are visible and correctable before a decision. Missing
  values are not an error and carry no warning: only one or two values may need an
  update. Accept persists the card's values and, when at least one is non-empty, enqueues
  the submit job (FR-10.2/10.6).
- **FR-10.11** The raw description is shown in a bordered Salt card with no internal
  scroll. Short Old/New pairs render side by side; long descriptions flow into 3–5
  balanced newspaper columns (2 below 1024 px). At 1280×800 the deck (header, card and
  actions) fits without page scrolling for every deviation. **Mobile, and descriptions
  too large to fit (over 1200 characters or 40 lines), use a compact preview** (the New
  block or the first 240 characters) plus a **Read full description** Salt dialog with
  the complete raw text. This is a size fallback, not a normal-case toggle: desktop
  descriptions within the limit are always shown in full.
- **FR-10.11** Decisions never gate sync or extraction. An accepted or rejected item is
  still reconciled with the list view like any other.

### FR-11 Retention & maintenance

- **FR-11.1** **Purge current data** deletes work items whose latest activity
  (`closed_at`, `last_seen` or `first_seen`) is older than 24 hours. It deletes that
  item's fields, attributes, refs, decisions, edits, events and terminal jobs (with their
  logs) with it. An item with an active job (`queued`, `running` or `blocked_auth`) is
  never deleted, and an active job row is never deleted even when its item is old.
  `sessions`, session events and approved history are out of scope.
- **FR-11.2** **Purge historical data** deletes approved-history rows whose accept
  decision is older than 3 months (90 days) and cascades every snapshot child row.
  Current work items and operational tables are out of scope.
- **FR-11.3** Both purges are idempotent: a second run with the same cutoff deletes zero
  rows. A dry run returns the same per-table counts without deleting anything.
- **FR-11.4** The purge API is available only through the hidden dev explorer
  (`/api/dev/db/purges`). `SF_DEV_TOOLS=0` and non-localhost requests get `404`, and the
  token-bearing `sessions` table is never read or written by either purge.
- **FR-11.5** The DB explorer shows both actions with a confirmation dialog, a dry-run
  count, and a success/error result. The dialog must state that the action cannot be
  undone and must require an explicit acknowledgement before the destructive button is
  enabled.
- **FR-11.6** `sync_runs` is not a purge scope. It is a bounded ring of the newest 20 rows
  per workflow, trimmed automatically in the insert transaction (FR-8.9).

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
| O-1 | ~~Which SF object and field label each of `loan_amount`, `property_value`, `tenure`, `emi_incl_hffc` is written to, and whether any value fans out to several objects.~~ **Resolved** — see the confirmed mapping below. | — |
| O-2 | ~~Exact label of the modal confirm button for `Implement`.~~ **Resolved** — there is no modal; the action is `button[name="Consumer_Loan_Deviation__c.Implemented"]` (label **Implemented**) on the deviation record, and the `Implemented__c` tick is both the precheck and the confirmation. | — |
| O-3 | Whether `z01`/`z03`/`z04` and `app/cancellations/` are live or dead scaffolding (proposed: delete). | Architecture |
| O-4 | ~~Wipe the legacy `data/app.db` for the new schema.~~ **Resolved** — wiped; `data/` now holds the workflow store. | — |
| O-5 | ~~Whether the deviation record page remains readable after implement.~~ **Resolved** — no record-page reconciliation; attribution is local (FR-6.12). | — |
| O-6 | ~~Archive or hard-delete closed deviations (FR-8.2).~~ **Resolved** — accepted history is snapshotted separately; current work items are purged after 24 hours and history after 90 days (FR-8.4–8.6, FR-11). | — |
| O-7 | ~~Should accepted items auto-submit once Phase 6 lands, or wait for an explicit
  submit action?~~ **Resolved** — accepted items with at least one non-empty value
  auto-submit; empty cards record the decision only. | — |

### Confirmed write mapping (O-1)

Each value is written to every target below; a submit fails rather than writing a
partial set (FR-6.3). Section names are the page areas the adapter scrolls to and are
used to disambiguate repeated labels.

| Value | Object | Section | Label |
|---|---|---|---|
| `property_value` | Opportunity | `LOAN PARAMETERS` | `Property Value Ex. Reg & ST(Financeable)` |
| `property_value` | Collateral | `Details` | `Property Value` |
| `property_value` | LMS 2.0 collateral | `Financials` | `Property Value` |
| `loan_amount` | Opportunity | `LOAN PARAMETERS` | `Loan Amount` |
| `loan_amount` | CL contract | `Contract` | `Loan Amount` |
| `loan_amount` | CL contract | `Funding` | `Financed Amount` |
| `loan_amount` | LMS 2.0 CL contract | `Loan amount` | `New value` |
| `tenure` | Opportunity | `LOAN PARAMETERS` | `Tenure (Yrs)` (months → years) |
| `tenure` | CL contract | `Contract` | `Term` (months) |
| `tenure` | LMS 2.0 CL contract | `Tenure` | `New value` (months) |
| `emi_incl_hffc` | Opportunity | `BUDGET ANALYSIS & SAVINGS PATTERN` | `EMIs & other fixed pmts inc HFFC Loan` |

The CL-contract record is a Lightning `loan__Loan_Account__c` page that embeds the
Classic Visualforce form (`tabbedLoanAccount`) in a `vfFrameId_*` iframe. Submission
opens the Lightning ref URL directly, resolves that iframe, and uses Classic inline edit
(double-click, clear the input, fill, verify, Save).

## Appendix C — Change log

- **v5.24** — the submission pipeline completes: after apply and validate it opens the
  deviation record, reads the `Implemented__c` tick and clicks **Implemented**; a tick
  already present is an external closure, not ours (FR-6.5–6.7, FR-6.14, FR-6.16; O-2
  resolved).

- **v5.23** — history rows expose the five object links as filterable columns; one
  `DataTable` implementation replaces the bespoke History, Jobs and Dev DB tables, with
  resizable persisted columns and container-only horizontal scrolling (FR-8.11,
  FR-9.20–9.24; FR-9.13 relaxed).

- **v5.22** — `sync_runs` is a bounded ring of 20 rows per workflow; the current purge
  also removes the purged item's terminal jobs and logs (FR-8.9, FR-8.10, FR-11.1,
  FR-11.6).

- **v5.21** — one standard table filter everywhere: text plus a multiselect checkbox
  dropdown for exact values, with a range variant for dates/durations. Jobs sends
  repeated values to the server; History gains per-column filters; the Dev DB result
  table filters every column. Future tables must reuse the shared components
  (FR-7.11, FR-8.8, FR-9.18/9.19).

- **v5.20** — approved-history snapshots are separated from current work items; the
  History tab reads the snapshot store. Manual purges keep current work items for 24
  hours and approved history for 90 days, with two confirmed actions in `/dev/db`
  (FR-8.4–8.7, FR-11). O-6 resolved.

- **v5.19** — refresh controls now pair the icon with context: **Sync now**,
  **Retry sync**, and **Reload deck**; the bare “Refresh” label is gone (FR-9.16).

- **v5.18** — header light/dark theme toggle: OS `prefers-color-scheme` on the first
  visit, explicit choice saved in `localStorage`; client-only (FR-9.15).

- **v5.17** — absence closure is retried and `needs_review` can defer through
  `absent_pending`; the reconciler revisits already-absent non-terminal items and the deck
  hides `present=false` rows (FR-6.11, FR-10.5).

- **v5.16** — Option C: **Accept & update** stores the card values, records the accept and
  enqueues the `SUBMIT` job when at least one value is non-empty. There is no confirmation
  dialog; `Shift+→` follows the same path. A failed accepted item returns to the deck in
  `needs_review`. O-7 resolved (FR-10.2/10.4/10.6/10.9).

- **v5.15** — the deck gains guarded keyboard decisions: `Shift+←` skips and `Shift+→`
  accepts, with the shortcut shown on the buttons; ignored while typing, in a dialog, with
  another modifier, and on auto-repeat (FR-10.9).

- **v5.14** — prefill is conservative: a field is suggested only when both Old and New
  blocks exist and the New value differs; empty operator values mean “no update” and are
  never written (FR-3.3, FR-5.6).

- **v5.13** — submit is write-and-verify, not conflict detection: the pre-read is for
  audit and idempotency only and never blocks a write, and a failed submit does not roll
  back partial writes; it records per-target truth and sends the item to `needs_review`
  (FR-6.2, FR-6.15).

- **v5.12** — mobile and oversized descriptions use a compact preview + Salt dialog for
  the full text; normal desktop descriptions remain fully visible in columns. The deck
  stays bounded on every viewport.

- **v5.12** — O-1 resolved: the confirmed write mapping is recorded above, including
  the two CL-contract targets for `loan_amount` and the Opportunity/LMS 2.0 tenure
  conversion. FR-6.14 adds the validate-only bring-up mode (no Implement click).

- **v5.11** — long descriptions flow into balanced columns (up to 5 on wide screens)
  instead of a toggle or scroll; every current card fits 1280×800 with no page scroll.

- **v5.10** — the description toggle is gone: Old and New blocks are shown together,
  side by side on wide screens, with no internal scroll; the deck still fits 1280×800.
  Fields and refs/ROI form the two columns below it.

- **v5.9** — the deck is two columns on large screens (description + fields | refs +
  ROI), the description shows only the New block by default with the Old block behind a
  toggle, and the whole deck fits 1280×800 without page scroll. Mobile stacks cleanly
  with no horizontal scroll.

- **v5.8** — description parsing prefers the New parameter block and never falls back
  to the Old block for a missing field; the card no longer warns about missing values
  (partial updates are normal).

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
