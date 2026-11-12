# API Design — Job Runtime (bounded waits, detailed logs, lease recovery)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Locked** | 2026-11-07 |
| **Approved by** | HarsimranVirk (user) |
| **Companions** | `docs/FR-deviations.md` (v5.31, FR-7.2/7.12/7.13/7.14), `docs/class-design-job-runtime.md`, `docs/data-model-job-runtime.md`, `docs/decisions-job-runtime.md` |

## 1. Summary

**No HTTP surface change.** There is no new route, request field, query parameter,
response field, status code or TypeScript type. The feature is observable only through
the existing job endpoints and payloads:

- `GET /api/jobs` — a job that hits the stale cap appears as `status: "failed"` with
  `error: "lease expired; max attempts reached"`.
- `GET /api/jobs/{id}` / the job log endpoint — includes the new step lines
  (FR-7.13).
- Existing duration, phase and error filters keep working unchanged.

The jobs table on the frontend already renders `status`, `error` and log lines, so no
React or `frontend/src/types.ts` change is required.

## 2. Contracts that stay fixed

| Endpoint | Method | Change |
|---|---|---|
| `/api/jobs` (paginated jobs table) | `GET` | None |
| `/api/jobs/{id}` | `GET` | None (same fields; new `error` text is an existing string field) |
| `/api/jobs/{id}/logs` (or the existing log read) | `GET` | None (new line content only) |
| `/api/deviations/{key}/jobs` (submission job creation) | `POST` | None |
| `/api/syncs` | `POST` | None |

Filters (`status`, `error`, `duration_min_ms`, …) and sort keys are unchanged: the new
error string is matched by the existing substring/`IN` filters.

## 3. Status and error cases

| Situation | HTTP | Payload | Notes |
|---|---|---|---|
| A job is requeued after its first expired lease | `200` on the next read | `status: "queued"`, `error: "lease expired; requeued"` | Same shape as today. |
| A job hits `MAX_JOB_ATTEMPTS` expired leases | `200` on the next read | `status: "failed"`, `error: "lease expired; max attempts reached"`, `finished_at` set | New terminal state path; no new status code. |
| A browser step exhausts its deadline | `200` on the next read | Job's normal outcome (`failed`, or `queued` for a retryable extraction) | The deadline is internal; it is not an HTTP error. |
| Operator lists jobs | `200` | Unchanged `JobPage` | Log/error strings are longer, no schema change. |

No `4xx` is introduced. A long wait never blocks an HTTP request: jobs still run on the
browser loop, and the API only enqueues or reads.

## 4. TypeScript types (`frontend/src/types.ts`)

Unchanged. The relevant existing types remain:

```ts
type JobStatus = "queued" | "running" | "blocked_auth" | "succeeded" | "failed" | "cancelled";
type JobKind = "extract" | "submit";

interface Job {
  id: number;
  workflow: string;
  item: string;
  kind: JobKind;
  status: JobStatus;
  phase: "extract" | "apply" | "validate" | "execute" | null;
  attempts: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  // …unchanged
}
```

The new `error` text and log lines fit the existing `string` fields; no union member is
added.

## 5. Compatibility

- Older rows keep their existing `error` values; the UI does not parse them.
- A client that filters on `status=failed` sees stale-cap failures automatically.
- No API version bump is needed because the contract is unchanged.
