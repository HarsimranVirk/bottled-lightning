# API Design — Loan Deviations

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v2 |
| **Date** | 2026-11-04 |
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

### `GET /api/deviations?status=&status=&decision=&q=&limit=50&offset=0`

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

Body: only the fields being changed; `null` discards a proposal.

```json
{ "loan_amount": "14,50,000", "tenure": null }
```

Statuses: `200` with the updated detail; `404` unknown item; `409` item not editable
(`submitting`, `implementing`, terminal); `422` value fails `normalise()`
(`{ "detail": { "code": "invalid_value", "field": "loan_amount", "message": "not an amount" } }`).

Changing any field moves the item to `editing`.

### `DELETE /api/deviations/{key}/field-values` → `200`

Discards all proposals and returns the item to `ready`.

### `POST /api/deviations/{key}/jobs` → `202`

Enqueues one `SUBMIT` job (FR-5.4).

```json
{ "jobId": 42, "kind": "submit", "status": "queued" }
```

- `409` when an active job already exists for the item (enforced by the partial unique
  index, not by a check-then-insert).
- `409` with `code: "login_required"` when `AuthGate` is paused.
- `422` when a `required` field has no value.

## 6. Jobs

### `GET /api/jobs?workflow=&kind=&status=&limit=100`

```json
[
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
    "error": null
  }
]
```

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

## 8. Updates (unchanged)

`GET /api/updates`, `POST /api/updates/checks`, `POST /api/updates/installations` keep
their current behaviour and payloads (`app/updater.py`).

## 9. TypeScript types (`frontend/src/types.ts`)

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
  error: string | null;
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
```

### Decision list filters

The deck calls `GET /api/deviations?status=ready&status=editing&status=needs_review
&decision=undecided&limit=200`. The list view passes the operator's selections. There is
no separate `/review` resource: a decision is a property of the item, so it is filtered
on the item collection and written as an item sub-resource.

## 10. Removed from v1

Deleted rather than deprecated: `/api/views*`, `/api/views/{id}/run`,
`/api/views/{id}/runs`, `/api/deviations/run`, `/api/deviations/runs`,
`/api/deviations/sync`, `/api/deviations/jobs` (replaced by the item-level sub-resource).

## 11. Acceptance checks

- Every handler is a thin adapter over `WorkItemService`/`AdminService`; no SQL and no
  Playwright in `app/api`.
- Route table matches §2–§8 exactly; no aliases.
- `GET /api/workflows` is enough to render the deviations page without hard-coded
  field lists.
- `PATCH` rejects unnormalisable values and never writes `proposed` without a validation
  pass.
- `POST …/jobs` cannot create a second active job (409 from the index, not a race).
- The TypeScript in §9 compiles with `strict` and is the only copy of these payloads.
