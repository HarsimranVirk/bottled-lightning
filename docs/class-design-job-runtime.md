# Class Design — Job Runtime (bounded waits, detailed logs, lease recovery)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Locked** | 2026-11-07 |
| **Approved by** | HarsimranVirk (user) |
| **Companions** | `docs/FR-deviations.md` (v5.31, FR-7.2/7.12/7.13/7.14), `docs/data-model-job-runtime.md`, `docs/api-job-runtime.md`, `docs/decisions-job-runtime.md`, `docs/class-design-deviations.md` |

## 1. Purpose

This feature stops a job from waiting for an unbounded multiple of a configured timeout
and makes every job's log say exactly which object, field and step it is on. It also
closes the recovery hole that resurrected a stuck job after a process restart.

It changes no table, endpoint, payload or TypeScript type. It changes the internals of
the wait helpers, the adapter seam, the job log content, the heartbeat and stale-lease
recovery.

## 2. Ownership boundaries

| Concern | Owner | Does not own |
|---|---|---|
| Real-time wait budget | `app/utils/dom.py` (`Deadline`, `bounded`, the wait helpers) | SF selectors, job status, retries |
| Per-object steps and selectors | `app/workflows/deviations_z02/adapters/*` | Retry policy, job status, item status |
| Phase/outcome narrative | pipeline classes (`DeviationsZ02Extraction`, `DeviationsZ02Submission`) | Selectors, raw page handles |
| Job status, heartbeat, final lease release | `app/jobs/worker.py` | Page selectors, domain outcomes |
| Claim/requeue/stale recovery | `app/jobs/dispatcher.py` + `app/core/repo/jobs.py` | Interpreting the failure |
| Persisted log lines | `app/jobs/logger.py` → `job_logs` | Formatting domain decisions |

The adapter layer gains a **log sink** dependency. It stays free of `WorkItemRepository`,
`JobRepository` and status decisions: it can only append a line through `JobLogger`.

## 3. Classes and Protocols

### 3.1 `Deadline` (`app/utils/dom.py`)

One monotonic budget for one bounded wait. It replaces every `waited += 500` counter.

```python
class Deadline:
    def __init__(self, timeout_ms: int) -> None: ...
    @property
    def expired(self) -> bool: ...
    def remaining_ms(self) -> int: ...
    def action_ms(self) -> float: ...        # remaining, never below 1 ms
    def sleep_s(self, cap_s: float) -> float: ...
```

- Uses `time.monotonic()`, so wall-clock changes cannot extend or shorten a wait.
- A negative/zero `timeout_ms` is already expired (tests use this).
- `action_ms()` is passed to Playwright's `timeout=` so an action can never outlive the
  budget that created it.
- `sleep_s(cap_s)` caps a retry sleep by the remaining budget.

**Collaborators:** `poll`, `click_first_visible`, `clear_and_fill`, `wait_for_rows`,
`wait_for_text`, `bounded`, and adapter-local loops (`_form_frame`, `_open_lms_tab`,
`_await_lms_rows`).

### 3.2 `bounded` (`app/utils/dom.py`)

```python
async def bounded[T](factory: Callable[[], Awaitable[T]], deadline: Deadline) -> T: ...
```

Runs one awaitable under `asyncio.timeout(deadline.action_ms() / 1000)`. The factory
form is deliberate: if the budget is already spent the coroutine is never created, so no
"coroutine was never awaited" warning and no work starts after the deadline. Expiry
raises the builtin `TimeoutError`; external task cancellation still propagates as
`CancelledError` and is never converted.

Callers that treat "not ready" as a normal outcome (`poll`, `wait_for_rows`,
`wait_for_text`) catch `TimeoutError` and return their documented false/None value. A
caller that must abort a target (`clear_and_fill`) lets it propagate to the adapter's
per-target `except Exception`, which returns `WriteOutcome.UNKNOWN`.

### 3.3 `LocatorLike` (`app/utils/dom.py`)

A structural Protocol with the subset of Playwright `Locator` the wait helpers use:
`count`, `nth`, `is_visible`, `click(timeout=...)`, `fill(value, timeout=...)`,
`input_value(timeout=...)`. Real `Locator` objects satisfy it, so adapters are unchanged
at the call site; unit tests use a fake without `cast`/`Any`.

### 3.4 Wait helpers (`app/utils/dom.py`)

All helpers keep their current public semantics and return types; only their time
accounting and per-action timeout change.

| Helper | Bounded behaviour |
|---|---|
| `poll(check, timeout_ms)` | Each predicate run is bounded by the remaining budget. Expiry returns `False`. A detached-locator exception is still "not yet". |
| `click_first_visible(locator, timeout_ms)` | Each `count`/`is_visible`/`click` is bounded by the remaining budget; no retry starts after expiry. Returns `False` on expiry. |
| `clear_and_fill(locator, value, timeout_ms)` | `fill("")`, `fill(value)` and `input_value()` each receive the remaining budget. |
| `wait_for_rows(locator, page, timeout_ms)` | Counts and sleeps use the real deadline; returns the last count. |
| `wait_for_text(page, text, timeout_ms)` | Body reads are capped by the remaining budget; returns `False` on expiry. |

### 3.5 `JobLogger` seam (`app/core/job_logger.py`)

The Protocol moves out of `app/core/workflow.py` into a leaf module so
`app/salesforce/adapters.py` can depend on it without a core↔salesforce import cycle.
`app/core/workflow.py` re-exports it (`from .job_logger import JobLogger`), so existing
imports keep working.

```python
class JobLogger(Protocol):
    def __call__(self, message: str) -> None: ...
```

`RepositoryLogger` remains the only implementation in production; it writes to the
process log and `job_logs` in the same call.

### 3.6 `ObjectAdapter` (`app/salesforce/adapters.py`)

Every method gains the job logger as its last parameter:

```python
class ObjectAdapter(Protocol):
    kind: str
    async def discover(self, tabs: TabProvider, context: DiscoveryContext,
                       log: JobLogger) -> Discovery: ...
    async def open(self, tabs: TabProvider, ref: PageRef) -> Page: ...
    async def read(self, page: Page, targets: Sequence[FieldTarget],
                   log: JobLogger) -> dict[FieldTarget, str | None]: ...
    async def write(self, page: Page, values: Mapping[FieldTarget, str],
                    log: JobLogger) -> dict[FieldTarget, WriteOutcome]: ...
```

`AdapterBase` mirrors the signatures and keeps raising `NotImplementedError`.

**Why the logger is a parameter, not module logging:** the user must see the lines in
the persisted job log after the fact. A module logger only reaches the process console.
**Why not a context variable:** the logger is per job; an explicit parameter keeps the
ownership visible and testable, and matches the existing pipeline seam.

### 3.7 Adapters (`app/workflows/deviations_z02/adapters/*`)

Each adapter owns the step vocabulary for its own page and writes lines in this shape:

```
<verb>: <object>: <field> [<section>]: <step and/or value>
```

- `<verb>` is `discover`, `read`, `apply` or `execute`.
- `<object>` is the adapter `kind` (`opportunity`, `cl_contract`, `collateral`,
  `lms2_cl_contract`, `lms2_collateral`, `deviation`).
- Failure branches (`no Edit control`, `frame not found`, `Save did not become
  clickable`, `read-back did not match`) are logged, not only raised/returned.
- `cl_contract` resolves a label cell with a bounded scan (`Deadline` +
  `_matching_labels(..., timeout_ms)`); the scan never walks the whole form once per
  poll tick without a deadline.

`DeviationRecordAdapter` additionally logs the final-action steps
(`is_implemented(page, log)`, `implement(page, log)`).

### 3.8 Pipelines

`DeviationsZ02Submission._read_all` gains a `stage` parameter (`precheck`, `readback`,
`preview`) so the same adapter read is labelled with the phase that requested it.
`run()` logs `phase: applying`, `phase: validating`, `phase: executing`, and
`_check_readback` logs each validated field. `DeviationsZ02Extraction._discover` logs the
adapter start, elapsed time and result summary around `adapter.discover(..., log)`.

The pipelines still translate outcomes to `SubmitOutcome`/`ExtractOutcome`; adapters
still never do.

### 3.9 `Worker` (`app/jobs/worker.py`)

- Uses `MAX_JOB_ATTEMPTS` from `app/core/status.py` (the single retry policy) instead of
  a private `_MAX_ATTEMPTS`.
- `_heartbeat(job_id, log)` catches and logs every exception, then keeps beating. It
  never lets a transient database error end the task and silently lose the lease.
- No wall-clock job timeout and no cancellation of pipeline work (D-08). Cleanup and
  outcome mapping are unchanged.

### 3.10 `JobRepository.requeue_stale` and `Dispatcher`

```python
def requeue_stale(self, max_attempts: int) -> int: ...
```

In one transaction:

1. `RUNNING` rows whose lease expired **and** `attempts >= max_attempts` become
   `FAILED`, with `finished_at` set, lease cleared, and error
   `lease expired; max attempts reached`.
2. Remaining expired `RUNNING` rows become `QUEUED`, with lease cleared and error
   `lease expired; requeued`.

Returns the number of rows requeued (the failed rows are not counted). The dispatcher
passes `MAX_JOB_ATTEMPTS` when it calls the repo from the idle claim loop. `BLOCKED_AUTH`
and `QUEUED` rows are untouched, so waiting for a manual login never consumes an
attempt.

## 4. End-to-end trace (the incident)

```
worker.execute(job)
  → Workflow.submission.run(item, tabs, log)
      → phase: applying
      → precheck: reading cl_contract (3 target(s)): …
          → ClContractAdapter.read(page, targets, log)
              → read: cl_contract: <field>: locating cell / value
      → apply: cl_contract (3 target(s)): …
          → ClContractAdapter.write(page, values, log)
              → apply: cl_contract: <field>: double-clicking
              → apply: cl_contract: <field>: filled '…'
              → apply: cl_contract: <field>: save clicked
              → apply: cl_contract: <field>: read-back '…'
      → phase: validating
      → readback: reading cl_contract (…)
          → ClContractAdapter.read(page, targets, log)
      → validated: <field>
      → phase: executing
          → execute: deviation: opening record page
          → execute: deviation: Implemented tick absent; clicking
          → execute: deviation: tick confirmed
```

Every wait on this path is bounded by `Deadline`; if the browser stalls, the log names
the last step and the job continues to its normal outcome/failure handling.

## 5. What does not change

- `ObjectAdapter.open`, `TabProvider`, `TabGroup`, the browser runtime and the
  single-loop/thread ownership.
- The tables, columns, indexes and retention of `jobs` / `job_logs`.
- Every HTTP route, payload and TypeScript type.
- The retry table for `TransientBrowserError`, `SessionExpired`, ambiguity, save
  rejection and already-closed.
- The `NEEDS_REVIEW` parking rules for submission failures.
