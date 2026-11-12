# Decision Register — Job Runtime (bounded waits, detailed logs, lease recovery)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Locked** | 2026-11-07 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | DOM wait accounting, adapter job logging, heartbeat, stale-lease recovery |
| **Companions** | `docs/FR-deviations.md` (v5.31, FR-7.2/7.12/7.13/7.14), `docs/class-design-job-runtime.md`, `docs/data-model-job-runtime.md`, `docs/api-job-runtime.md` |

## Context

A submission job ran for more than 20 minutes and appeared to repeat `read → precheck
→ apply → apply` after a process restart. The log stopped after
`apply: cl_contract (3 target(s))`, inside `ClContractAdapter.write`.

The wait helpers counted a nominal 500 ms per retry iteration while an individual
Playwright action could block for its full 60 s timeout. `click_first_visible` passed
the full timeout to every click, and `poll` re-scanned every `td.labelCol` in the
classic form on every tick. A nominally 60 s wait therefore composed into hours.

After a restart the row stayed `running` until its 300 s lease expired, then
`requeue_stale()` requeued it regardless of `attempts`, so the job resurrected and
re-ran forever. The heartbeat task also had no exception handling, so one failed
database write could silently lose the lease while the job was still running.

This register records the decisions needed to fix that, and only that.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | Every retrying wait measures a monotonic deadline and passes the *remaining* budget to each action instead of counting nominal intervals. | Keep the `waited += 500` counters and add a job-level wall-clock timeout. | The counter is the root cause of the 20-minute hang; a job timeout would hide it, kill work mid-write and contradict FR-7.7. | `app/utils/dom.py`, adapter-local wait loops | locked |
| D-02 | `poll()` bounds each predicate run with the remaining budget and returns `False` on expiry. | Rely on Playwright's per-call timeouts only. | The predicate itself (`_saved` scanning the classic form) was the slow part; bounding only the individual locator call leaves the loop unbounded. | `app/utils/dom.py`, `tests/test_dom.py` | locked |
| D-03 | `click_first_visible()` and `clear_and_fill()` give each click/fill/read the remaining budget, and no retry starts after expiry. | Keep passing the full `timeout_ms` to every attempt. | Two Save buttons × a 60 s click × 120 nominal iterations is hours for a call that claims 60 s. | `app/utils/dom.py`, `tests/test_dom.py` | locked |
| D-04 | `cl_contract` label resolution is budget-aware and stops walking the form when the budget is spent. | Keep rescanning every `td.labelCol` on every poll tick. | The full-form scan multiplied the nominal poll timeout by the number of labels and their per-cell timeouts. | `app/workflows/deviations_z02/adapters/cl_contract.py` | locked |
| D-05 | Every adapter receives the job logger (`discover`/`read`/`write`) and logs object, field, step and outcome; the pipelines log phase, precheck/readback stage and validation. | Keep only group-level pipeline logs, or log only to the process console. | The operator needs the persisted job log to name the last step before a hang; module logging is not visible after the fact. | `app/core/job_logger.py`, `app/salesforce/adapters.py`, all six adapters, both pipelines, `tools/smoke_submit.py`, tests | locked |
| D-06 | A heartbeat exception is logged to the job and retried; the heartbeat task never dies silently. | Let the task die and rely on lease expiry. | Silent lease loss lets a second slot claim and execute the same job concurrently while the first still runs. | `app/jobs/worker.py`, `tests/test_jobs.py` | locked |
| D-07 | `requeue_stale()` fails a running job whose expired lease has reached `MAX_JOB_ATTEMPTS` (2) instead of requeueing it forever. | Requeue every expired lease indefinitely. | This is the cross-restart "eventually fail" guarantee; without it a restart resurrects the same job forever. | `app/core/repo/jobs.py`, `app/jobs/dispatcher.py`, `app/core/status.py`, `tests/test_repositories.py` | locked |
| D-08 | No wall-clock job timeout and no cancellation of a running job in this change. | Add a 10-minute per-attempt watchdog (the rejected Option B). | The actual unbounded paths are fixed; a watchdog would force-kill mid-write, need an FR-7.7 amendment and could cut a submit between write and read-back. | — | locked |
| D-09 | `MAX_JOB_ATTEMPTS = 2` is defined once in `app/core/status.py` and shared by the worker retry policy and the stale sweep. | Keep the worker's private `_MAX_ATTEMPTS` and a second literal in the repo. | Two literals would drift; one constant keeps the retry policy and recovery cap consistent. | `app/core/status.py`, `app/jobs/worker.py`, `app/jobs/dispatcher.py` | locked |

## What stays the same

- No schema, migration, route, payload or TypeScript type change.
- `ObjectAdapter.open`, `TabProvider`, `TabGroup`, the browser runtime and the single
  browser loop/thread.
- The outcome mapping for `TransientBrowserError`, `SessionExpired`, ambiguity, save
  rejection and already-closed; `NEEDS_REVIEW` parking from the submission pipeline.
- `BLOCKED_AUTH` behaviour: a job waiting for a manual login is never failed by stale
  recovery, and the wait itself is not a job timeout.
- The existing 24-hour job/log retention and the `sync_runs` ring.

## Amendments

None.
