# Frontend Design — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v1 |
| **Date** | 2026-11-04 |
| **Feature** | Loan deviations (Z02) |
| **Companions** | `docs/FR-deviations.md`, `docs/api-deviations.md`, `docs/refactor-plan-deviations.md` |
| **Implemented by** | refactor Phase 8 (`frontend/src`); not built yet |

The backend is a state machine; the frontend is a **view of that machine**. The goal of
this document is that no screen can ever show a state the database cannot produce, and no
interaction can imply a result that has not been confirmed by the server.

**The workflow abstraction is a backend implementation detail.** The operator sees
concrete tabs — *Home*, *Deviations Z02*, *Jobs* — never a workflow picker. The pages read
`GET /api/workflows` for labels and fields, but each page is written for its tab; adding a
second workflow later means adding a second tab deliberately, not genericising this one.

---

## 1. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| UI kit | Salt DS (`@salt-ds/core`, `@salt-ds/theme`, `@salt-ds/icons`) | already chosen; accessible primitives, no bespoke CSS system |
| Server state | **TanStack Query** | list/detail/jobs/sync are server state; caching, polling and invalidation are the whole game |
| Routing | **react-router** (`/`, `/deviations-z02`, `/deviations-z02/:key`, `/jobs`) | concrete tabs, deep-linkable item detail |
| Forms | controlled inputs + server-side validation | the API returns `422 {code, field, message}`; duplicating rules client-side guarantees drift |
| Types | **generated** from OpenAPI into `frontend/src/types.ts` | single source of truth; a drift check is cheap |
| Component tests | Vitest + React Testing Library + **MSW** | fast, no browser, mocks the documented contract |
| Visual/E2E | Playwright (already a dependency) | screenshots per state; the review mechanism for agents and humans |
| Language | TypeScript `strict`, no `any` | matches AGENTS.md |

Rejected: Redux (server state dominates), Storybook (a `/dev/states` harness gives most of
the value), client-side business rules (the backend owns them).

## 2. UX flows

### 2.1 Happy path

```
open app
  └─ session valid ──► list (7 rows, last sync < 30 s)
        └─ open item ──► detail: fields, attributes, refs
              └─ edit 2 fields ──► "Save changes" ──► PATCH
                    └─ submit ──► confirm dialog ──► POST job (202)
                          └─ status cycles: submitting → applying →
                             validating → executing → completed
                                └─ item leaves the working list (present=false)
```

### 2.2 Unhappy paths that must be designed, not discovered

| Situation | Screen behaviour |
|---|---|
| No session | list/detail replaced by `AuthCard`; one primary action ("Log in") |
| Login window open | `AuthCard` shows "Finish logging in in the browser window" with a spinner and a cancel hint |
| Session expired mid-use | global `SyncBanner` (danger): dispatch paused, every mutating control disabled, "Log in" button |
| Sync invalid (header ≠ rows) | `SyncBanner` (warning): "last refresh untrusted (header 12 ≠ rows 11)"; rows shown from the last valid sync with their age |
| Empty list | `EmptyState`: "No deviations in the list view" + last sync time |
| Item skipped | terminal chip + reason (e.g. "multiple LMS2 CL contracts") |
| Item closed externally | terminal chip "Closed" + "left Salesforce without us implementing it" |
| Submission failed | `needs_review` banner, job link with logs, "resubmit" disabled until values are reviewed |
| Field rejected by SF | field-level error on the cell, others retain their values |
| Polling error | non-blocking banner "reconnecting", keep last data, retry with backoff |

## 3. Screens and the state matrix

Every row below must be renderable from fixtures in the `/dev/states` harness before the
screen is built against the API.

### 3.1 Home / auth

| State | Content | Actions |
|---|---|---|
| `none` | explanation of the manual login | **Log in** |
| `login_running` | spinner, "browser window opened" | (disabled) |
| `valid` | cookie count, saved-at, last event | Re-login, Clear session |
| `expired` | danger callout | **Log in** |

### 3.2 Deviations Z02 list

| State | Content | Actions |
|---|---|---|
| loading | 5 skeleton rows | — |
| empty | `EmptyState` + last sync | Refresh |
| ready | table: status, key, loan amount, property value, tenure, EMI, approved at | Open, filter, search |
| invalid sync | warning banner + last valid sample age | Refresh |
| paused | danger banner replaces the filter bar's primary action | Log in |
| filter miss | "No items match" + clear filters | Clear |

### 3.3 Item detail (drawer or full page on narrow screens)

| State | Editable fields | Banner |
|---|---|---|
| `ready` | yes | — |
| `editing` (dirty) | yes | footer: "2 unsaved changes" · Discard / Save |
| `submitting` | no | info: "queued for submission" |
| `applying` / `validating` / `executing` | no | progress: phase name |
| `needs_review` | yes (values stay visible) | danger: reason + last job |
| `completed` / `closed` / `skipped` | no | terminal chip + reason + attribution |

Sections, in order: **status header** (key, chip, approved at, record link) → **editable
values** (grouped by target object, read-only when the status forbids editing) →
**attributes** (description, ROI, product type — read-only) → **objects** (five refs;
missing refs render "not found" instead of being hidden) → **history** (edits + events).

### 3.4 Jobs

| State | Content |
|---|---|
| empty | "nothing has run yet" |
| running | phase chip + elapsed + lease owner |
| failed | error + expandable log lines |
| succeeded / cancelled | timestamp + result |

### 3.5 History

Closed/skipped items with reason, attribution and decided-at. Filter by status and date.

## 4. Component tree

```
App
└── AppShell                     layout, header, global banners
    ├── SyncBanner               session + sync health (one place, always visible)
    ├── AuthCard                 replaces content when session is none/expired
    ├── DeviationsPage          route "/deviations-z02" (the Z02 tab)
    │   ├── FilterBar            status select, search box, refresh
    │   ├── ItemsGrid            table; owns row rendering only
    │   │   └── ItemRow          cells + StatusChip
    │   │       ├── StatusChip   text + colour, never colour alone
    │   │       └── FieldCell    read-only or editable cell
    │   └── ItemDrawer           route "/deviations-z02/:key"
    │       ├── FieldGroup       editable values for one target object
    │       ├── AttributeList    read-only extracted values
    │       ├── PageRefList      five object links, missing ones marked
    │       ├── HistoryList      edits + events
    │       └── SubmitBar        dirty count, Save, Discard, Submit
    └── QueueBar                 concurrency, in-flight, pause state
```

Responsibilities are deliberately narrow: `FieldCell` never fetches, `ItemRow` never
mutates, `WorkflowPage` owns all queries for its route.

## 5. Client data model

Server state is the only state that matters; everything else is UI.

| Query key | Endpoint | Refresh | Notes |
|---|---|---|---|
| `["session"]` | `GET /api/sessions` | 10 s | drives the global banner and muting |
| `["workflows"]` | `GET /api/workflows` | on boot | catalogue + labels, never refetched during a session |
| `["sync", workflow]` | `GET /api/syncs?workflow=` | 10 s | header/rows/valid/warning |
| `["items", workflow, filters]` | `GET /api/deviations` | 10 s | list |
| `["item", workflow, key]` | `GET /api/deviations/{key}` | 10 s, paused while editing | detail |
| `["jobs", filters]` | `GET /api/jobs` | 2 s while the panel is open | queue |
| `["job", id]` | `GET /api/jobs/{id}/logs` | 2 s while visible | expanded job |

Rules:

- **Polling stops** when `document.hidden` and resumes on visibility.
- **Mutations invalidate; they never patch the cache by hand**, except the field draft
  below. The server is the only writer of status.
- **Editing** keeps a `Record<fieldKey, string>` draft in `ItemDrawer`; it is sent as one
  `PATCH` on Save, and resent/discarded explicitly otherwise. Polling for the item is
  paused while the draft is dirty so a refresh cannot visually overwrite typing.
- **Optimistic updates**: none. Saving shows a spinner; the authoritative values arrive
  with the PATCH response (the endpoint returns the full detail).
- **`localStorage`** keeps only UI preferences (filters, drawer width) and the last known
  session *display* state. It is never a source of truth.

## 6. Interaction spec

1. **Edit** — click a cell (or focus + Enter) → input with the current value; `Esc` cancels
   that cell, `Enter`/blur stages the change. Staged changes are shown in the footer
   ("2 unsaved changes").
2. **Save** — one `PATCH` with only changed fields. On `422 invalid_value` the message is
   attached to that field and the drawer stays dirty; other fields keep their drafts.
3. **Discard** — `DELETE …/field-values`, then refetch the item.
4. **Submit** — enabled only when there is at least one proposed value and the item is
   `ready`/`editing`/`needs_review`. Opens a confirmation dialog naming the item and the
   changed fields (FR-9.9). On `409 login_required`, the dialog switches to "log in first".
5. **Disabled rules** are derived from `status` + `activeJob`, never from a local
   `isSaving` flag that can desync.
6. **Keyboard** — the whole edit → save → submit path is reachable without a mouse;
   focus returns to the edited cell after save.
7. **Confirmations** — submit and "clear session" only. Editing is undoable by discard, so
   it does not need a modal.

## 7. Visual rules

- Salt DS spacing/typography tokens only; no custom CSS framework and no inline colours.
- **Status is a word first**: `StatusChip` renders text plus tone (info/success/warning/
  danger/neutral); the tone never carries meaning alone.
- One table, one drawer. Desktop-first (operator laptop, ≥1280 px); the drawer becomes a
  full page below 900 px; the list is read-only-usable at 390 px.
- Amounts and tenure are right-aligned and rendered exactly as stored (Indian grouping);
  the client never reformats money.
- Timestamps are shown in local time with a relative hint ("12:46 pm · 3 min ago").
- No dark mode in v1; Salt's theme provider stays in place so it can be added later.

## 8. Accessibility and feedback

- WCAG 2.2 AA: focus visible, 4.5:1 text contrast, 24 px targets, no motion required.
- The drawer traps focus and returns it on close; `Esc` closes it.
- Job/status changes announced through `aria-live="polite"` (no per-second spam: only
  status changes, not elapsed time).
- Every icon-only control has an accessible name.
- Errors are announced and linked to their field with `aria-describedby`.

## 9. API consumption and types

- `frontend/src/types.ts` is **generated** — `tools/export_openapi.py` writes a snapshot,
  `openapi-typescript` turns it into types. Hand edits are overwritten; CI runs the
  generation and fails on a dirty diff.
- The generated names are aliased into the UI vocabulary in `src/api.ts`
  (`ItemRow`, `ItemDetail`, `JobView`, …) so component code never imports raw schema paths.
- One thin `src/api.ts` module owns every `fetch`, unwraps `{detail: {code, message}}` into
  `ApiError {status, code, message}`, and is the only place that knows URL shapes.
- TanStack Query hooks live in `src/queries.ts`, one per query key above.

## 10. Testing and review

| Layer | Tool | What it covers |
|---|---|---|
| Pure helpers | Vitest | `StatusChip` mapping, `formatAmount` (identity), error unwrapping, dirty diff |
| Components | RTL + MSW | disabled rules per status, field error rendering, submit confirmation, paused banner |
| States | `/dev/states` route + Playwright screenshots | every row of the matrix, at 390/768/1280 |
| Contract | generated types + MSW handlers | a field rename on the backend breaks typecheck |

Visual review loop: build → run → screenshot the state harness at three widths → inspect
the images → fix. Screenshots are the acceptance evidence for a UI change.

Not tested in CI: real Salesforce behaviour (covered by the backend's live smoke tools).

## 11. Implementation slices

Each slice ends with screenshots of its matrix rows and a typecheck.

**Slice A — read-only** (auth, banners, the Deviations Z02 tab, detail, jobs). No *item* mutations;
session login/logout and a manual refresh are included because the screen is unusable
without them. Proves the contract, the state mapping and the layout. Acceptance: all matrix rows render from
fixtures; a valid session shows the 7 real deviations.

**Slice B — editing.** Draft map, `PATCH`, field-level `422`, discard, dirty guard.
Acceptance: editing `tenure` to an invalid value shows the server message on that field;
saving a valid value updates the row without a manual refresh.

**Slice C — submission.** Confirmation dialog, `POST …/jobs`, status polling with phases,
`needs_review` recovery, terminal states. Acceptance: submitting a prepared item shows
`submitting → … → completed` and the item leaves the working list; a paused session shows
`login_required` and disables submission.

Phase 8 is done when A–C ship, all matrix rows have screenshots, and
`npm --prefix frontend run typecheck && npm --prefix frontend run test` pass.

## 12. Open questions

| ID | Question | Default if unanswered |
|---|---|---|
| F-1 | Bulk actions (select many → submit)? | No; one item at a time |
| F-2 | Should closed/skipped items stay on the main list behind a filter, or live only in History? | Filter on the main list ("All statuses" default hides terminal) |
| F-3 | Table or card layout on narrow screens? | Table until 768 px, then stacked rows |
| F-4 | Do we want a "refresh now" button in the UI? | Yes; it calls `POST /api/syncs` |
| F-5 | Password-less re-login reminder (banner when snapshot age > N days)? | Show age; warn after 12 h |
