# Frontend Design — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v3.9 |
| **Date** | 2026-11-05 |
| **Feature** | Loan deviations (Z02) |
| **Companions** | `docs/FR-deviations.md`, `docs/api-deviations.md`, `docs/refactor-plan-deviations.md` |
| **Implemented by** | refactor Phase 8 (`frontend/src`); Slice A and the review deck (D) are live |

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
| UI kit | Salt DS (`@salt-ds/core`, `@salt-ds/theme`, `@salt-ds/icons`) | **every** control and surface: Tabs, ToggleButtonGroup, Table, Dropdown, FormField, Input, Card, Panel, Banner, StatusIndicator, Button; CSS is layout only |
| Server state | **TanStack Query** | list/detail/jobs/sync are server state; caching, polling and invalidation are the whole game |
| Routing | **react-router** (`/`, `/deviations-z02`, `/deviations-z02/:key`, `/jobs`) | concrete tabs, deep-linkable item detail |
| Forms | controlled inputs + server-side validation | the API returns `422 {code, field, message}`; duplicating rules client-side guarantees drift |
| Types | **generated** from OpenAPI into `frontend/src/types.ts` | single source of truth; a drift check is cheap |
| Component tests | Vitest + React Testing Library + **MSW** | fast, no browser, mocks the documented contract |
| Visual/E2E | Playwright (already a dependency) | screenshots per state; the review mechanism for agents and humans |
| Language | TypeScript `strict`, no `any` | matches AGENTS.md |
| Review decisions | local, append-only SQLite rows (`accept`/`reject`/undo) | one operator, reversible, no SF write; see FR-10 |
| Deck input | **Skip / Accept buttons only** | gestures could accept by mistake; the buttons span the card width |

Rejected: Redux (server state dominates), Storybook (a `/dev/states` harness gives most of
the value), client-side business rules (the backend owns them).

## 2. UX flows

### 2.1 Happy path

```
open app
  └─ session valid ──► review deck (undecided, decidable items)
        ├─ Accept button ──► PATCH values + POST decision ──► next card
        ├─ Skip button   ──► POST decision ────────────────► next card
        ├─ undo (U) ──► DELETE decision ──► the card returns
        └─ details ──► item panel: values, attributes, refs, history
              └─ edit 2 fields ──► "Save changes" ──► PATCH
                    └─ submit ──► confirm dialog ──► POST job (202)
                          └─ status cycles: submitting → applying →
                             validating → executing → completed
                                └─ item leaves the working list (present=false)
```

Accept/reject is deliberately **not** a submit: it records the decision that feeds the
submitter once Phase 6 exists (FR-10.6). The confirmation dialog belongs to submit, not
to a reversible decision.

### 2.2 Unhappy paths that must be designed, not discovered

| Situation | Screen behaviour |
|---|---|
| Healthy session + valid sync | **no banner**; the footer shows version, session, sync age and rows |
| No session | list/detail replaced by `AuthCard`; one primary action ("Log in") |
| Login window open | `AuthCard` shows "Finish logging in in the browser window" with a spinner and a cancel hint |
| Session expired mid-use | global `SyncBanner` (danger): dispatch paused, every mutating control disabled, "Log in" button |
| Sync invalid (header ≠ rows) | `SyncBanner` (warning): "last refresh untrusted (header 12 ≠ rows 11)"; rows shown from the last valid sync with their age |
| Empty deck | "Deck complete" card + last sync age |
| Item skipped | terminal chip + reason (e.g. "multiple LMS2 CL contracts") |
| Item closed externally | terminal chip "Closed" + "left Salesforce without us implementing it" |
| Submission failed | `needs_review` banner, job link with logs, "resubmit" disabled until values are reviewed |
| Field rejected by SF | field-level error on the cell, others retain their values |
| Polling error | non-blocking banner "reconnecting", keep last data, retry with backoff |
| Decision write fails | banner over the deck (danger) with the server message; the card stays, nothing is hidden |
| Two decisions race | the server returns the winner; the deck refetches and shows whatever is current |
| Session expired while deciding | decisions stay enabled (they are local); loop shows the auth banner and submit/refresh are disabled |

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

### 3.2 Deviations Z02 — review deck (default)

The tab opens on the deck, in the shape of the legacy `Deck.tsx`: one card at a time,
accepted/skipped/to-review tallies, then Skip and Accept. The header keeps the
**Deck / History** toggle; history is section 3.2b.

| State | Card content | Actions |
|---|---|---|
| loading | one card skeleton; tallies show the last snapshot | — |
| ready | record link + status, approval date, *Pages to update* (Opportunity, CL, collateral, LMS2), raw description panel, ROI grid, four editable values; only values that changed between the description's Old and New blocks are prefilled | Skip, Accept |
| needs_review | same card + the failure reason above the description | Skip, Accept |
| partial values | unchanged, missing or equal Old/New values start blank; the current SF value (`lastSynced`) is never shown as a prefill or hint; no warning | Accept allowed (FR-10.10) |
| description | bordered Salt card: full text in Old/New columns on desktop; compact preview + **Read full description** dialog on mobile or above 1200 chars / 40 lines | decide |
| editing a value | input shows Indian grouping (amounts) or months; the draft is local until Accept | Skip discards the draft |
| decision in flight | Skip/Accept disabled until the PATCH + decision finish | — |
| decision failed | card stays, the server message appears above it | Retry |
| leaving | card slides out right (accept) or left (skip) for 420 ms | — |
| complete | `Deck complete 🎉`, accepted/skipped counts, **Replay skipped**, Refresh | undo all skips |
| paused session | deck still usable (decisions + proposals are local) + global auth banner | Skip, Accept |

Below the description the card splits into **read-only data on the left** (Pages to
update, ROI) and the **four editable values on the right**; Skip/Accept span the card.
On narrow screens the card stacks in that order: description, read-only, editable.

Card order: newest `last_seen` first, the same order as the list. "next up: <key>" names
the card behind the top one. **Accept** PATCHes the card's cleaned values as proposals
(amounts are grouped on screen, digits on the wire) and then records the decision;
**Skip** records only the decision. Neither writes to Salesforce (FR-10.2).

### 3.2b Deviations Z02 — accepted history (toggle)

The history is the record of what the deck approved: one row per **accepted** deviation,
newest decision first. It is not a working list and has no deck actions.

| State | Content | Actions |
|---|---|---|
| loading | Salt table skeleton | — |
| ready | Salt Table: Deviation (SF link), Decided (chip + time), Status, SF approval, four values | Open detail, search |
| empty | "No deviations have been accepted yet." | — |
| search miss | "No approved deviations match this search." | Clear search |
| page overflow | `1–25 of N`, page buttons, rows-per-page | Page |

The search field is a Salt `FormField`; pagination is server-side ordered by the newest
decision (`sort=decision&order=desc`). Clicking a row opens the Salt detail panel; the
deviation number is an absolute Salesforce link. Undo decision in the detail returns the
item to the deck and removes it from history on the next refetch.

### 3.3 Item detail (drawer or full page on narrow screens)

| State | Editable fields | Banner |
|---|---|---|
| `ready` | yes | — |
| `editing` (dirty) | yes | footer: "2 unsaved changes" · Discard / Save |
| `submitting` | no | info: "queued for submission" |
| `applying` / `validating` / `executing` | no | progress: phase name |
| `needs_review` | yes (values stay visible) | danger: reason + last job |
| `completed` / `closed` / `skipped` | no | terminal chip + reason + attribution |

The header also shows the current decision (`Accepted` / `Rejected`, with reason) and an
**Undo decision** button while the item is decidable. History appends decisions above the
edit list, newest first.

Sections, in order: **status header** (key, chip, approved at, record link) → **editable
values** (grouped by target object, read-only when the status forbids editing) →
**attributes** (description, ROI, product type — read-only) → **objects** (five refs;
missing refs render "not found" instead of being hidden) → **history** (edits + events).

### 3.4 Footer (every screen)

| State | Content | Actions |
|---|---|---|
| connecting | brand + version, "connecting…" | — |
| healthy | brand + `v<version>`, "Session active · synced 12s ago · 7 rows" | Refresh |
| untrusted sync | "Session active · last refresh untrusted" (banner carries the detail) | Refresh |
| session invalid | "Session expired" / "Session not set" (banner carries the login) | Refresh |

The footer is the only always-present status surface; the top banner appears only when
something is wrong. Keeping the version here means no release can be confused with a
stale UI.

### 3.5 Jobs

A standard data table: sortable headers, **column filters in a second header row**
(directly under each column label), server-side pagination, and a log panel for the
selected job. Filter controls are Salt `Input`/`Dropdown`; the row is part of the table
head, not a separate form above it.

Columns: **ID · Status · Kind · Phase · Item · Started · Duration · Error**. The row is
selectable; the log panel below shows the selected job and its full error.

| State | Content |
|---|---|
| loading | table skeleton; previous rows keep their place |
| empty (no jobs) | "nothing has run yet" |
| empty (filtered) | "no jobs match" + Clear filters |
| running | live duration from the server's `durationMs`; phase column shows the step |
| failed | error column truncated + full error in the log panel |
| succeeded / cancelled | finished time and final duration |
| page overflow | pagination bar: `1–25 of 137`, page size, Prev/Next |
| selected | row highlighted; log panel open below |

Filters: id (contains), status / kind / phase (selects), item (contains), started
from/to (UTC dates), duration min/max (seconds), error (contains). Changing any filter
or sort resets to page 1. Sortable headers toggle asc/desc and expose `aria-sort`.

## 4. Component tree

```
App
└── AppShell                     layout, header, global banners
    ├── SyncBanner               session + sync health (one place, always visible)
    ├── AuthCard                 replaces content when session is none/expired
    ├── DeviationsPage          route "/deviations-z02" (the Z02 tab)
    │   ├── ViewToggle          Salt ToggleButtonGroup: Deck (default) / History
    │   ├── DecisionDeck         one card, tallies, replay, exit animation
    │   │   └── DecisionCard     Salt card: refs, description, ROI grid, FormField values
    │   ├── HistoryTable         Salt Table of accepted deviations + search + pagination
    │   └── ItemDrawer           route "/deviations-z02/:key" (Salt Panel)
    │       ├── FieldGroup       values grouped by target object
    │       ├── AttributeList    read-only extracted values
    │       ├── PageRefList      five object links, missing ones marked
    │       └── HistoryList      decisions + edits
    ├── QueueBar                 concurrency, in-flight, pause state
    ├── AppFooter                version, session/sync status, refresh
    └── JobsPage                 filters + table + pagination + logs
```

Responsibilities are deliberately narrow: `FieldCell` never fetches, `ItemRow` never
mutates, `DeviationsPage` owns all queries for its route.

## 5. Client data model

Server state is the only state that matters; everything else is UI.

| Query key | Endpoint | Refresh | Notes |
|---|---|---|---|
| `["session"]` | `GET /api/sessions` | 10 s | drives the global banner and muting |
| `["version"]` | `GET /api/version` | on boot | footer only; never refetched |
| `["workflows"]` | `GET /api/workflows` | on boot | catalogue + labels, never refetched during a session |
| `["sync", workflow]` | `GET /api/syncs?workflow=` | 10 s | header/rows/valid/warning |
| `["items", workflow, filters, offset]` | `GET /api/deviations` | 10 s | deck (all rows for the tallies) and history (`decision=accept&sort=decision`) |
| `["item", workflow, key]` | `GET /api/deviations/{key}` | 10 s, paused while editing | detail |
| `["jobs", filters, page, size, sort, order]` | `GET /api/jobs` | 2 s while visible | paginated queue |
| `["job", id]` | `GET /api/jobs/{id}/logs` | 2 s while visible | expanded job |
| `["items", …]` mutation | `POST` / `DELETE …/decisions` | on action | invalidates the list and item keys |
| `["items", …]` mutation | `PATCH …/field-values` | on accept with edits | stores the card's proposals, then the decision |

Rules:

- **Polling stops** when `document.hidden` and resumes on visibility. A failed request
  does **not** stop polling: the next interval retries, so a restarted backend recovers
  within one tick instead of freezing the last snapshot on screen.
- **Mutations invalidate; they never patch the cache by hand**, except the field draft
  below. The server is the only writer of status.
- **Editing** keeps a `Record<fieldKey, string>` draft in `ItemDrawer`; it is sent as one
  `PATCH` on Save, and resent/discarded explicitly otherwise. Polling for the item is
  paused while the draft is dirty so a refresh cannot visually overwrite typing.
- **Optimistic updates**: none. Saving shows a spinner; the authoritative values arrive
  with the PATCH response (the endpoint returns the full detail).
- **Deck decisions** follow the same rule: the card stays until the server confirms, then
  the query is invalidated and the next card becomes the top card. The animation starts
  only after the response, so a failed request never looks like a decision.
- **A decided card is not re-shown** by a poll: the deck query excludes decided items, so
  a slow refresh cannot resurrect a card the operator dismissed.
- **`localStorage`** keeps only UI preferences (filters, drawer width) and the last known
  session *display* state. It is never a source of truth.

## 6. Interaction spec

1. **Decide** — the **Skip** and **Accept** buttons decide; both span half the card
   width and show their shortcut (`Skip (Shift+←)`, `Accept (Shift+→)`). There is no drag
   or swipe gesture (FR-10.9). Accept sends the card's values first
   (`PATCH …/field-values`)
   and then the decision, so one accept is two ordered requests; Skip sends only the
   decision. The card slides out after the server confirms. No modal: decisions are
   reversible (FR-10.3), and *Replay skipped* restores every skip when the deck is empty.
2. **Edit** — click a cell (or focus + Enter) → input with the current value; `Esc` cancels
   that cell, `Enter`/blur stages the change. Staged changes are shown in the footer
   ("2 unsaved changes").
3. **Save** — one `PATCH` with only changed fields. On `422 invalid_value` the message is
   attached to that field and the drawer stays dirty; other fields keep their drafts.
4. **Discard** — `DELETE …/field-values`, then refetch the item.
5. **Submit** — enabled only when there is at least one proposed value and the item is
   `ready`/`editing`/`needs_review`. Opens a confirmation dialog naming the item and the
   changed fields (FR-9.9). On `409 login_required`, the dialog switches to "log in first".
6. **Undo decision** — `DELETE …/decisions` from the deck footer or the detail banner; the
   item becomes undecided and re-enters the deck on the next refetch.
7. **Disabled rules** are derived from `status` + `activeJob`, never from a local
   `isSaving` flag that can desync. A decision in flight disables only the deck actions.
8. **Keyboard** — deck: `Shift+→` accept, `Shift+←` reject, `U` undo, `Enter` details. The
   deck shortcuts are ignored while a text field or an open dialog has focus, with another
   modifier held, and on key auto-repeat, so a stray key cannot accept a deviation.
   Detail: the whole edit → save → submit path is reachable without a mouse; focus returns
   to the edited cell after save. Keys are ignored while a text field has focus.
9. **Confirmations** — submit and "clear session" only. Decisions, editing and undo are
   reversible and do not need a modal.

## 7. Visual rules

- Salt DS spacing/typography tokens only; no custom CSS framework and no inline colours.
- **Status is a word first**: `StatusChip` renders text plus tone (info/success/warning/
  danger/neutral); the tone never carries meaning alone.
- One deck, one table, one drawer. Desktop-first (operator laptop, ≥1280 px); the drawer
  becomes a full page below 900 px; card, table and drawer are usable at 390 px.
- **Salt only.** No custom control styles: Tabs, ToggleButtonGroup, Table, Dropdown,
  FormField, Input, Card, Panel, Banner, StatusIndicator and Button cover every surface.
  CSS is limited to layout, responsive column hiding and motion.
- **High density.** Page padding 10/16 px, headings 20/17/14 px, data text 11–12 px,
  layout gaps 8–16 px (not 24–32), table cells 4–5 px, card padding 10–12 px, the deck
  description block in a bordered Salt Card, full width: Old/New pairs side by side;
  descriptions over 500 characters flow into 3–5 balanced columns on desktop. Mobile, or
  text over 1200 characters / 40 lines, shows a compact preview (New block or first 240
  characters) with a **Read full description** Salt dialog. Never internally scrollable.
- **No horizontal page scrolling at 390/768/1280 px.** The shell is border-box; filters
  wrap; the list drops to Status + Deviation at 600 px instead of scrolling sideways.
  Long values wrap (`overflow-wrap: anywhere`), never widen the page.
- Deck card: Salt `Card elevation="raised"`, **max-width 960 px** on large screens
  (two content columns), full width below `lg`. One card at a time; the next item is
  named below it, not stacked behind it. At 1280×800 the header, card and actions fit
  without page scrolling; below `lg` the card stacks and the page scrolls vertically.
  Skip and Accept are full-width halves of the card (40 px tall) so they are the obvious
  action and cannot be confused with a gesture.
- The exit animation is transform-only (slide left/right + ≤14° rotate) and disabled
  under `prefers-reduced-motion`, where the card simply disappears after the response.
- Amounts are edited as digits and shown with Indian grouping; tenure is shown in months.
  The client never rounds or guesses units: a bare `10.0` stays 10 months (legacy rule).
- Timestamps are shown in local time with a relative hint ("12:46 pm · 3 min ago").
- No dark mode in v1; Salt's theme provider stays in place so it can be added later.

## 8. Accessibility and feedback

- WCAG 2.2 AA: focus visible, 4.5:1 text contrast, 24 px targets, no motion required.
- The deck is fully operable with buttons and keys; swiping is additive. The action
  buttons are always in the tab order. Decision results go to an `aria-live="polite"`
  line ("Accepted … · deck complete"), never to a modal.
- **All data text is selectable.** There is no drag gesture, so selecting the
  description, ROI values or refs never moves the card.
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
| Tables | RTL + MSW | header filters, sorting, pagination, empty/error states |
| States | `/dev/states` route + Playwright screenshots | every row of the matrix, at 390/768/1280 |
| Responsive | `tools/audit_layout.py` | fails when any route needs horizontal scrolling at 390/768/1280 |
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
`login_required` and disables submission. *Blocked on O-1/O-2.*

**Slice E — jobs table** (done). Duration column, filters **in the column headers**,
sortable headers, server-side pagination and the log panel. Acceptance: filter/sort/page
combinations hit the server, the total reflects the filters, and a running job's
duration ticks.

**Slice F — history** (done). The general list view is replaced by the accepted-deviations
history table (Salt Table, newest decision first, search + server pagination). The deck
completion card links to it.

**Slice D — review deck** (done). Default deck view in the legacy card shape, accept/reject
decisions, editable prefilled values saved as proposals on accept, full-width Skip/Accept
buttons only, tallies, replay skipped, decision chips in history, decision history
in the detail. The card carries everything: no separate *Details* button, the SF approval
date is always shown (dash when empty), and the deviation number is an absolute Salesforce
record link.
Acceptance: a real 7-row list is decidable card by card; an edited value is stored as a
proposal before the decision; deciding removes the card and survives a reload; replay
restores every skipped card; a failed decision leaves the card in place.

Phase 8 is done when A–D ship, all matrix rows have screenshots, and
`npm --prefix frontend run typecheck && npm --prefix frontend run test` pass.

## 12. Open questions

| ID | Question | Default if unanswered |
|---|---|---|
| F-1 | Bulk actions (select many → submit)? | No; one item at a time |
| F-2 | Should closed/skipped items stay on the main list behind a filter, or live only in History? | Filter on the main list ("All statuses" default hides terminal) |
| F-3 | Table or card layout on narrow screens? | Table until 768 px, then stacked rows |
| F-4 | Do we want a "refresh now" button in the UI? | Yes; it calls `POST /api/syncs` |
| F-5 | Password-less re-login reminder (banner when snapshot age > N days)? | Show age; warn after 12 h |
| F-6 | Should accepted items submit automatically once Phase 6 exists? | No; acceptance queues, the operator submits explicitly (O-7) |
| F-7 | Ask for a reject reason inline, or leave it optional and silent? | **Resolved**: the deck matches legacy and skips silently; the API still accepts a reason for other surfaces |
