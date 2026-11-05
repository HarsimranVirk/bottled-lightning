# API Design — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v2.9 |
| **Date** | 2026-11-05 |
| **Feature** | Loan deviations (Z02) |
| **Companions** | `docs/FR-deviations.md`, `docs/class-design-deviations.md`, `docs/data-model-deviations.md` |
| **Implemented by** | `app/api/*` (refactor Phase 7) — live |

This document is the source of truth for the HTTP surface and the matching
TypeScript types. The routes below are implemented in `app/api/` and mounted by
`app.main`; the pre-refactor `app/routes.py` is no longer wired.

---

## 1. Conventions

- Plural nouns only, no verb segments: actions are HTTP methods on sub-resources.
- Selection by path parameter (`/api/deviations/{key}`); filters, pagination and format
  in query parameters.
- JSON everywhere; timestamps are ISO-8601 UTC strings; amounts and tenure are the
  strings the operator sees (Indian grouping), not numbers.
- Unknown workflow/item → `404`. Illegal state (e.g. a second submission while one is
  active) → `409`. Invalid input → `422` (FastAPI validation). Auth required → `409`
  with `detail.code = "login_required"` (the app cannot proxy SF credentials, so this
  is a state conflict, not a 401 challenge).
- Long operations never block a request: enqueue a job and return `202`.

Error body:

```json
{ "detail": "deviations_z02/Deviation-…: already has an active SUBMIT job" }
```

Structured errors add a `code` so the UI can branch without string matching:

```json
{ "detail": { "code": "login_required", "message": "manual login required" } }
```

## 2. Workflows

### `GET /api/workflows`

Registered workflows, enough for the frontend to render a generic page.

```json
[
  {
    "name": "deviations_z02",
    "route": "deviations",
    "label": "Loan Deviations",
    "listUrl": "https://hffc.lightning.force.com/lightning/o/Consumer_Loan_Deviation__c/list?filterName=Z2_Loan_para_pricing1",
    "refKinds": ["opportunity", "cl_contract", "collateral", "lms2_cl_contract", "lms2_collateral"],
    "fields": [
      { "key": "loan_amount", "label": "Loan Amount", "valueType": "amount", "required": false, "targets": ["cl_contract"] },
      { "key": "property_value", "label": "Property Value", "valueType": "amount", "required": false, "targets": ["collateral"] },
      { "key": "tenure", "label": "Tenure", "valueType": "months", "required": false, "targets": ["cl_contract"] },
      { "key": "emi_incl_hffc", "label": "EMI & other fixed payments incl. HFFC Loan", "valueType": "amount", "required": false, "targets": ["cl_contract"] }
    ],
    "terminalLabels": { "completed": "Implemented", "closed": "Closed", "skipped": "Skipped" }
  }
]
```

## 3. Sessions (auth)

### `GET /api/sessions`

```json
{
  "state": "valid",
  "paused": false,
  "cookies": 34,
  "savedAt": "2026-11-04T19:04:12+00:00",
  "lastEvent": { "event": "login", "detail": "34 cookies", "at": "2026-11-04T19:04:12+00:00" }
}
```

`state`: `none` | `valid` | `expired`. `paused` mirrors `AuthGate.paused`.

### `POST /api/sessions` → `202`

Starts a headed manual login (the operator logs in; the snapshot is then saved).

```json
{ "state": "login_running" }
```

### `DELETE /api/sessions` → `204`

Clears every snapshot and forces the next job to require a login.

## 4. Sync

### `GET /api/syncs?workflow=deviations_z02`

```json
{
  "workflow": "deviations_z02",
  "capturedAt": "2026-11-04T19:32:00+00:00",
  "headerTotal": 7,
  "rowsRead": 7,
  "valid": true,
  "warning": null,
  "added": 0,
  "updated": 7,
  "closed": 0
}
```

If no run exists yet, `200` with `null` fields.

### `POST /api/syncs` → `202`

Requests an immediate refresh instead of waiting for the 30 s cycle.

## 5. Items (the unified view)

### `GET /api/deviations?status=&status=&decision=&sort=&order=&q=&limit=50&offset=0`

```json
{
  "workflow": "deviations_z02",
  "count": 1,
  "total": 7,
  "rows": [
    {
      "key": "Deviation-03112026-486382",
      "status": "ready",
      "present": true,
      "epoch": 1,
      "recordUrl": "https://hffc.lightning.force.com/lightning/r/a2fS2000000fR5tIAE/view",
      "approvedAt": "4/11/2026 6:46 pm",
      "reason": null,
      "fields": {
        "loan_amount": { "extracted": "13,00,000", "lastSynced": "13,00,000", "proposed": null, "applied": null, "status": "extracted" },
        "property_value": { "extracted": "22,50,000", "lastSynced": "22,50,000", "proposed": null, "applied": null, "status": "extracted" },
        "tenure": { "extracted": null, "lastSynced": null, "proposed": null, "applied": null, "status": "extracted" },
        "emi_incl_hffc": { "extracted": "16,256", "lastSynced": "16,256", "proposed": null, "applied": null, "status": "extracted" }
      },
      "decision": null,
      "activeJob": { "id": 12, "kind": "extract", "status": "running", "phase": "extract" }
    }
  ]
}
```

- `status` filters by `WorkItemStatus` and is repeatable
  (`?status=ready&status=needs_review`). Omitted means every status.
- `decision` filters by review decision: `accept`, `reject`, or `undecided` (no decision,
  or the latest decision was undone). Omitted means any.
- `q` matches the key or the reason.
- `sort` is `last_seen` (default) or `decision`; `order` is `asc`/`desc`.
- `recordUrl` is an absolute Salesforce URL. Rows stored before the sync fix may still
  hold a root-relative path; the UI resolves it against the workflow's `listUrl`.

### `GET /api/deviations/history`

The approved-history read model. Returns `HistoryPageView`: the same counters as
`ItemsPageView` but rows are `HistoryRowView`, which adds `refs`. Every row comes from
`approved_deviations`, not `work_items`. Rows are always newest accept first; only
accepted snapshots exist, so there is no decision filter. `activeJob` is always `null`.
The current-item list keeps the smaller `ItemRowView`, so the polled deck endpoint does
not pay for refs it never shows.

Query parameters (all optional and composable):

| Parameter | Meaning |
|---|---|
| `q` | legacy global contains match on key, item reason or accept note |
| `key` | deviation key contains |
| `key_in` | repeated exact deviation keys |
| `status_text` | status display contains |
| `status` | repeated exact snapshot statuses |
| `approved_at` | SF approval display contains |
| `approved_at_in` | repeated exact SF approval strings |
| `decided_after`, `decided_before` | accept date range (`YYYY-MM-DD`), inclusive |
| `field` | repeated `field_key:value` exact field values |
| `field_text` | repeated `field_key:text` contains field values |
| `ref` | repeated `kind:value` exact linked-object names |
| `ref_text` | repeated `kind:text` contains linked-object names |
| `limit`, `offset` | page size (default 25, max 500) and offset |

The field filters use the same value precedence as the table: `proposed`, else
`extracted`, else `applied`. Amount values are compared raw; the UI strips Indian
grouping commas before sending a text filter. `total` is the filtered set, not the page.

The `ref` kinds are the five object kinds the workflow registers: `opportunity`,
`cl_contract`, `collateral`, `lms2_cl_contract`, `lms2_collateral`. Each `(kind, value)`
pair becomes its own `EXISTS` against `approved_deviation_refs`, matching on `name`; text
and selections in one column compose with AND, columns with AND, values within one
selection with OR — the same rule as every other column (FR-9.18, FR-9.21).

```json
// GET /api/deviations/history?ref_text=opportunity:006&ref=collateral:CJID-0000280688
{
  "workflow": "deviations_z02",
  "count": 1,
  "total": 1,
  "rows": [
    {
      "key": "Deviation-03112026-486382",
      "status": "completed",
      "present": false,
      "epoch": 1,
      "recordUrl": "https://…/view",
      "approvedAt": "2026-11-03",
      "reason": null,
      "fields": { "loan_amount": { "…": "…" } },
      "decision": { "decision": "accept", "reason": null, "at": "2026-11-04T18:20:00Z" },
      "activeJob": null,
      "refs": [
        { "kind": "opportunity", "name": "006…", "url": "https://…/006…/view" },
        { "kind": "cl_contract", "name": "LAI-00533155", "url": "https://…/a4b…/view" },
        { "kind": "collateral", "name": "CJID-0000280688", "url": "https://…/a49…/view" },
        { "kind": "lms2_cl_contract", "name": "LAI-00533155", "url": "https://…/LMS2…" },
        { "kind": "lms2_collateral", "name": "CJID-0000280688", "url": "https://…/LMS2…" }
      ]
    }
  ]
}
```

A kind with no stored ref is simply absent from `refs`; the UI renders `—` for that
column. `refs` is never `null`.

### `GET /api/deviations/history/{key}`

The snapshot detail: same `ItemDetailView` shape as the current item detail, including
attributes, refs, edits and the accept decision. It stays available after the current
work item is purged. `404` with `code: "unknown_history_item"` when no snapshot exists.

### `GET /api/deviations/{key}`

Adds attributes and refs, grouped for the detail panel:

```json
{
  "key": "Deviation-03112026-486382",
  "status": "ready",
  "recordUrl": "https://…/view",
  "fields": { "loan_amount": { "…": "…" } },
  "decision": { "decision": "accept", "reason": null, "at": "2026-11-04T18:20:00Z" },
  "attributes": {
    "description": "Old Paramaters\nLA-13,00,000…",
    "requested_roi": null,
    "ideal_roi": "13.25%",
    "updated_roi": null,
    "requested_variance": null,
    "product_type": "Home Loan (Resale)",
    "record_id": "a2fS2000000fR5tIAE"
  },
  "refs": [
    { "kind": "opportunity", "name": "Shaban Khan", "url": "https://…/Opportunity/006…/view" },
    { "kind": "cl_contract", "name": "LAI-00533155", "url": "https://…/a5B…/view" },
    { "kind": "collateral", "name": "CJID-0000280688", "url": "https://…/a49…/view" },
    { "kind": "lms2_cl_contract", "name": "LAI-00533155", "url": "https://…/CL_Contract_Detail?c__loanId=…" },
    { "kind": "lms2_collateral", "name": "CJID-0000280688", "url": "https://…/Collateral_Detail?c__collateralId=…" }
  ],
  "edits": [ { "field": "tenure", "oldValue": null, "newValue": "240", "at": "…" } ],
  "decisions": [ { "decision": "accept", "reason": null, "at": "2026-11-04T18:20:00Z" } ]
}
```

### `POST /api/deviations/{key}/decisions` → `200`

Record an accept/reject review decision. This never writes to Salesforce and never
changes the pipeline status (FR-10.2).

```json
{ "decision": "reject", "reason": "tenure and EMI do not match the sanction letter" }
```

- `decision` is `accept` or `reject` (422 `invalid_decision` otherwise). `reason` is
  optional and may be omitted or null.
- Returns the updated detail, whose `decision` is the new decision and whose
  `decisions` list gains the row.
- `404` unknown item; `409` item is not decidable (`submitting`, in-flight or terminal).
- A decision is allowed on `ready`, `editing` and `needs_review`; the item leaves the
  deck but keeps its status and proposals.

### `DELETE /api/deviations/{key}/decisions` → `200`

Undo the current decision. Appends a `pending` row (nothing is deleted), so the audit
trail keeps the reversal; the returned detail has `decision: null` and the item is
undecided again. `404` unknown item; `409` when the item is not decidable.

### `PATCH /api/deviations/{key}/field-values`

Body: only the fields being changed; `null`, `""` or a whitespace-only string discards a
proposal and means “no update”. Only non-empty proposed values are ever written.

```json
{ "loan_amount": "14,50,000", "tenure": null }
```

Statuses: `200` with the updated detail; `404` unknown item; `409` item not editable
(`submitting`, `implementing`, terminal); `422` value fails `normalise()`
(`{ "detail": { "code": "invalid_value", "field": "loan_amount", "message": "not an amount" } }`).

Changing any field moves the item to `editing`. A `needs_review` item is first returned
to `ready` (the state machine has no direct `needs_review → editing` edge), then to
`editing`; its values stay editable so a failed submission can be corrected.

### `DELETE /api/deviations/{key}/field-values` → `200`

Discards all proposals and returns the item to `ready`.

### `POST /api/deviations/{key}/jobs` → `202`

Enqueues one `SUBMIT` job (FR-5.4) and writes the edit audit (`work_item_edits`) for
every proposed value before returning.

```json
{ "jobId": 42, "kind": "submit", "status": "queued" }
```

- `409` when an active job already exists for the item (enforced by the partial unique
  index, not by a check-then-insert).
- `409` with `code: "login_required"` when `AuthGate` is paused.
- `422` when there are no proposed values to submit.

A `SUBMIT` job applies and validates the values, then implements the deviation: it opens
the deviation record, checks the `Implemented__c` tick and clicks **Implemented** when the
tick is absent, confirming on the tick (FR-6.5–6.7). An already-ticked deviation returns
`already_closed` and is closed externally on the next refresh (FR-6.16). The response
shape is unchanged. A rejected write, a read-back mismatch, or an unconfirmed click fails
the job and moves the item to `needs_review`; there is no automatic rollback, so the item
reason and job logs identify which targets were already written (FR-6.15). The API never
exposes the Salesforce page or the button; it only enqueues the job.

## 6. Jobs

### `GET /api/jobs`

A paginated, filterable, sortable page of jobs. Every filter composes; `total` is the
count of the filtered set, not the page.

Query parameters:

| Parameter | Meaning |
|---|---|
| `workflow` | exact workflow |
| `kind`, `status`, `phase` | repeatable exact enum values |
| `status_text`, `kind_text`, `phase_text` | enum display contains |
| `id` | job id contains the text |
| `id_in` | repeated exact job ids |
| `item` | deviation number contains the text |
| `item_in` | repeated exact deviation numbers |
| `error` | error text contains the text |
| `error_in` | repeated exact error strings |
| `started_after`, `started_before` | UTC date (`YYYY-MM-DD`), inclusive |
| `duration_min_ms`, `duration_max_ms` | duration range in milliseconds |
| `sort` | `id` (default) · `status` · `kind` · `phase` · `item` · `created` · `started` · `finished` · `duration` · `attempts` · `error` |
| `order` | `asc` / `desc` (default `desc`) |
| `limit`, `offset` | page size (default 25, max 200) and offset |

The frontend sends repeated values for `kind`, `status`, `phase`, `id_in`, `item_in`
and `error_in`. A single value still works, so existing clients are unaffected. Text
contains and exact-value selections compose with AND.

```json
{
  "count": 1,
  "total": 137,
  "rows": [
    {
      "id": 42,
      "workflow": "deviations_z02",
      "item": "Deviation-03112026-486382",
      "kind": "submit",
      "status": "running",
      "phase": "apply",
      "attempts": 1,
      "leaseOwner": "81324:w0",
      "createdAt": "…", "startedAt": "…", "finishedAt": null,
      "durationMs": 4200,
      "error": null
    }
  ]
}
```

`durationMs` is `finished_at - started_at` for a terminal job and the live elapsed
time for a running one; `null` when the job never started (queued/cancelled).
Unknown enum values, sort keys or orders are `422`.

### `GET /api/jobs/{id}` / `GET /api/jobs/{id}/logs`

```json
{ "job": { "…": "…" }, "logs": ["submit start: …", "apply: cl_contract", "…"] }
```

### `DELETE /api/jobs/{id}` → `204`

Cancels a **queued** job only; running jobs are not interrupted mid-write (FR-7.7).
`409` for a running/succeeded/failed job.

## 7. Workers / queue

### `GET /api/workers`

```json
{ "concurrency": 3, "inFlight": 1, "paused": false, "counts": { "queued": 2, "running": 1, "succeeded": 40 } }
```

### `PATCH /api/workers`

```json
{ "concurrency": 2 }
```

`422` outside `1..5`. Shrinking lets running jobs finish.

### `GET /api/version`

The running app version, shown in the footer on every screen. Cheap, cached and
independent of the update check.

```json
{ "version": "0.4.5" }
```

## 8. Dev tools (dev-only)

Enabled by default but hidden from the main UI; set `SF_DEV_TOOLS=0` to disable.
Requests are localhost-only unless `SF_DEV_TOOLS_ALLOW_REMOTE=1`. All routes return
`404` when disabled or remote.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/dev/db/tables` | table names, columns, row counts; `sessions` is never listed |
| `POST` | `/api/dev/db/queries` | one read-only statement; preview capped at 5,000 rows |
| `POST` | `/api/dev/db/exports` | the same statement as a `csv` or real `xlsx` file |
| `POST` | `/api/dev/db/purges` | manual current (24 h) or history (90 d) purge |

```json
// POST /api/dev/db/queries
{ "sql": "SELECT * FROM work_items LIMIT 50", "limit": 500 }
```

```json
// response
{
  "columns": ["item_key"],
  "rows": [["Deviation-03112026-486382"]],
  "rowCount": 1,
  "truncated": false,
  "durationMs": 3
}
```

```json
// POST /api/dev/db/exports
{ "sql": "SELECT * FROM work_items", "format": "xlsx" }
```

The export is an attachment named `bottled-lightning-export-<timestamp>.<ext>`.
`textarea` query errors return `422`. The `sessions` table is blocked by a SQLite
authorizer and must never be added to the allowlist. The full design and safety rules are
in `docs/dev-tools.md`.

### `POST /api/dev/db/purges`

Manual retention. The server computes the cutoff; the body cannot override it.

```json
{ "scope": "current", "dryRun": true }
```

- `scope=current` deletes work items last active more than 24 hours ago (except items
  with an active job) plus their fields, attributes, refs, decisions, edits and events. It
  also deletes their terminal `jobs` (`succeeded`, `failed`, `cancelled`) and those jobs'
  `job_logs`; `queued`, `running` and `blocked_auth` jobs are never deleted.
- `scope=history` deletes approved snapshots accepted more than 90 days ago plus their
  child rows.
- `dryRun` returns the counts without deleting. A real run is one transaction.
- `409` with `code: "purge_failed"` if SQLite rejects the transaction; `404` when dev
  tools are disabled or the request is not localhost.

The payload is unchanged: `deleted` is an open `dict[str, int]`, so the two new table keys
need no schema edit and the confirm dialog renders them automatically. The frontend
regenerates `types.ts` as usual, but the TypeScript shape is identical.

```json
{
  "scope": "current",
  "cutoff": "2026-11-04T18:20:00Z",
  "dryRun": false,
  "deleted": {
    "work_items": 3,
    "work_item_fields": 12,
    "work_item_attributes": 30,
    "work_item_refs": 15,
    "work_item_edits": 2,
    "work_item_events": 4,
    "item_decisions": 3,
    "jobs": 5,
    "job_logs": 17
  },
  "total": 91
}
```

## 9. Updates (unchanged)

`GET /api/updates`, `POST /api/updates/checks`, `POST /api/updates/installations` keep
their current behaviour and payloads (`app/updater.py`).

## 10. TypeScript types (`frontend/src/types.ts`)

These are the shapes the frontend consumes. The committed `frontend/src/types.ts` is
**generated** from `tools/export_openapi.py` + `openapi-typescript`, so this section
documents intent and the generator is the mechanism. A schema change that is not
regenerated fails `npm run typecheck`.

```ts
export type WorkItemStatus =
  | "present" | "extracting" | "ready" | "editing" | "submitting"
  | "applying" | "validating" | "executing" | "absent_pending"
  | "needs_review" | "completed" | "closed" | "skipped";

export type ValueType = "amount" | "months" | "text";
export type FieldStatus = "extracted" | "proposed" | "applied" | "rejected";

export interface FieldView {
  extracted: string | null;
  lastSynced: string | null;
  proposed: string | null;
  applied: string | null;
  status: FieldStatus;
}

export interface WorkflowField {
  key: string;
  label: string;
  valueType: ValueType;
  required: boolean;
  targets: string[];
}

export interface WorkflowView {
  name: string;
  route: string;
  label: string;
  listUrl: string;
  refKinds: string[];
  fields: WorkflowField[];
  terminalLabels: Record<string, string>;
}

export interface JobView {
  id: number;
  workflow: string;
  item: string;
  kind: "extract" | "submit";
  status: "queued" | "running" | "blocked_auth" | "succeeded" | "failed" | "cancelled";
  phase: "extract" | "apply" | "validate" | "execute" | null;
  attempts: number;
  leaseOwner: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  error: string | null;
}

export interface JobsPage {
  count: number;
  total: number;
  rows: JobView[];
}

export type DecisionKind = "accept" | "reject";
export interface DecisionView {
  decision: DecisionKind;
  reason: string | null;
  at: string;
}

export interface ItemRow {
  key: string;
  status: WorkItemStatus;
  present: boolean;
  epoch: number;
  recordUrl: string | null;
  approvedAt: string | null;
  reason: string | null;
  fields: Record<string, FieldView>;
  decision: DecisionView | null;
  activeJob: JobView | null;
}

export interface PageRefView { kind: string; name: string; url: string }

export interface ItemDetail extends ItemRow {
  attributes: Record<string, string | null>;
  refs: PageRefView[];
  edits: { field: string; oldValue: string | null; newValue: string | null; at: string }[];
  decisions: DecisionView[];
}

export interface ItemsPage {
  workflow: string;
  count: number;
  total: number;
  rows: ItemRow[];
}

export interface HistoryRow extends ItemRow {
  refs: PageRefView[];
}

export interface HistoryPage {
  workflow: string;
  count: number;
  total: number;
  rows: HistoryRow[];
}

export type PurgeScope = "current" | "history";
export interface PurgeResult {
  scope: PurgeScope;
  cutoff: string;
  dryRun: boolean;
  deleted: Record<string, number>;
  total: number;
}

export interface JobQuery {
  workflow?: string;
  kind?: string[];
  status?: string[];
  phase?: string[];
  statusText?: string;
  kindText?: string;
  phaseText?: string;
  id?: string;
  idIn?: string[];
  item?: string;
  itemIn?: string[];
  error?: string;
  errorIn?: string[];
  startedAfter?: string;
  startedBefore?: string;
  durationMinMs?: number;
  durationMaxMs?: number;
  sort?: string;
  order?: string;
  limit?: number;
  offset?: number;
}

export interface HistoryQuery {
  q?: string;
  key?: string;
  keyIn?: string[];
  statusText?: string;
  statuses?: string[];
  approvedAt?: string;
  approvedAtIn?: string[];
  decidedAfter?: string;
  decidedBefore?: string;
  fields?: { key: string; value: string }[];
  fieldText?: { key: string; text: string }[];
  limit?: number;
  offset?: number;
}

export interface SyncView {
  workflow: string;
  capturedAt: string | null;
  headerTotal: number | null;
  rowsRead: number;
  valid: boolean;
  warning: string | null;
  added: number;
  updated: number;
  closed: number;
}

export interface SessionView {
  state: "none" | "valid" | "expired";
  paused: boolean;
  cookies: number | null;
  savedAt: string | null;
  lastEvent: { event: string; detail: string; at: string } | null;
}

export interface QueueView {
  concurrency: number;
  inFlight: number;
  paused: boolean;
  counts: Record<string, number>;
}

export interface VersionView {
  version: string;
}
```

### Decision list filters

The deck calls `GET /api/deviations?status=ready&status=editing&status=needs_review
&decision=undecided&limit=200`. The list view passes the operator's selections. There is
no separate `/review` resource: a decision is a property of the item, so it is filtered
on the item collection and written as an item sub-resource. History is the exception: it
is a separate read model served by `/api/deviations/history`, so a current-data purge
cannot blank it.

## 11. Removed from v1

Deleted rather than deprecated: `/api/views*`, `/api/views/{id}/run`,
`/api/views/{id}/runs`, `/api/deviations/run`, `/api/deviations/runs`,
`/api/deviations/sync`, `/api/deviations/jobs` (replaced by the item-level sub-resource).

## 12. Acceptance checks

- Every handler is a thin adapter over `WorkItemService`/`AdminService`; no SQL and no
  Playwright in `app/api`.
- Route table matches §2–§8 exactly; no aliases.
- `GET /api/workflows` is enough to render the deviations page without hard-coded
  field lists.
- `PATCH` rejects unnormalisable values and never writes `proposed` without a validation
  pass.
- `POST …/jobs` cannot create a second active job (409 from the index, not a race).
- The TypeScript in §9 compiles with `strict` and is the only copy of these payloads.
