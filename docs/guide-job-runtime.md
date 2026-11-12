# Guide — Job Runtime (bounded waits, detailed logs, lease recovery)

| | |
|---|---|
| **Status** | Built |
| **Date** | 2026-11-07 |
| **Decision register** | `docs/decisions-job-runtime.md` (v1, LOCKED) |
| **Design** | `docs/class-design-job-runtime.md`, `docs/data-model-job-runtime.md`, `docs/api-job-runtime.md` |

## What it does

- A browser step can no longer run for hours because its retry loop counted nominal
  ticks. Every wait is bounded by real elapsed time (FR-7.12).
- Every job log names the phase, object, field and step. If a job stalls, the last line
  says whether it was opening a page, entering edit mode, filling, clicking Save or
  waiting for the read-back (FR-7.13).
- A job that keeps losing its lease is failed after **two attempts** with
  `lease expired; max attempts reached`, instead of being resurrected on every restart
  (FR-7.14).
- A failed heartbeat is logged to the job and retried; the job does not silently lose
  its lease and duplicate itself.
- There is **no wall-clock job kill**: running SF work is still never force-killed
  mid-write. The bounded waits are what stop the hang.

No table, endpoint, payload or frontend type changed.

## How to use it

Nothing new to start. The app runs as before:

```bash
source .venv/bin/activate
python -m app.main                 # backend + SPA on :8765
python -m app.salesforce.login     # after an expired session
```

Watch a job in the UI's jobs screen. The log panel now shows lines such as:

```
precheck: reading cl_contract (3 target(s)): Loan Amount [Contract], Term [Contract], Financed Amount [Funding]
read: cl_contract: Loan Amount [Contract]='8,00,000.00'
precheck: cl_contract: read done in 1.2s
apply: cl_contract (3 target(s))
apply: cl_contract: Term [Contract]: double-clicking cell
apply: cl_contract: Term [Contract]: filled '120'
apply: cl_contract: Term [Contract]: clicking Save
apply: cl_contract: Term [Contract]: save clicked
apply: cl_contract: Term [Contract]: saved
apply: cl_contract: done in 3.4s
phase: validating
readback: reading cl_contract (3 target(s)): …
validated: tenure
phase: executing
execute: deviation: Implemented tick absent; clicking
execute: deviation: tick confirmed
```

Useful reads:

```bash
curl 'http://localhost:8765/api/jobs?status=failed&limit=25'
curl 'http://localhost:8765/api/jobs/123'            # status, attempts, error
curl 'http://localhost:8765/api/jobs/123/logs'       # the step lines
```

After a failure, inspect the item in the review deck. Fix the cause, then submit it
again; a failed submission is never retried automatically.

## Configuration and state

- No new environment variable. `MAX_JOB_ATTEMPTS = 2` is a code constant in
  `app/core/status.py`.
- The existing `request_timeout_ms` (60 s) is still the budget for one browser action;
  it is now applied as a real deadline rather than per retry.
- State lives in the existing `jobs` and `job_logs` tables of `data/app.db` (or the OS
  app-data dir in an installed build). Retention is unchanged (24 h for terminal jobs
  and their logs).
- No migration: the row shape is unchanged.

## Five likely failure modes

1. **`lease expired; max attempts reached`** — the job lost its lease twice (usually a
   killed process or a wedged browser). It is now terminal. Read its log, fix the cause,
   and re-submit the item. Restarting the app will not resurrect it.
2. **`apply: <object>: <field>: Save did not become clickable`** — Salesforce rendered
   the inline editor but the Save control stayed covered. The item is parked in
   `needs_review`; open the record, check the value manually, and resubmit.
3. **`read-back did not match` / `writes not accepted`** — Salesforce rejected or
   reformatted a write. The field is marked rejected and the item is in `needs_review`.
   Do not retry blindly; inspect the per-target values in the log. The opportunity log
   names what the page actually showed (`still editing=True` means SF kept the editor
   open, usually a validation error on the record; otherwise the field rendered a
   different value).
4. **`Classic form frame not found`** — the CL contract page did not embed the
   `tabbedLoanAccount` form. Retry once; if it persists, the SF page layout changed and
   the adapter needs an update.
5. **`lease heartbeat failed`** — a SQLite write failed while the job was running (for
   example a lock held longer than the busy timeout). The heartbeat retries and the job
   normally continues. Repeated lines mean database contention: check for a second
   process, a stuck backup, or a very large purge.

If the log stops without one of these lines, capture the process console too. A truly
wedged browser can still require a restart; after the restart the stale-lease cap marks
the job `failed` on its second attempt instead of re-running it forever. If it happens
repeatedly, the last log line identifies the step to investigate.

## Where the design lives

- Requirements: `docs/FR-deviations.md` FR-7.2, FR-7.12–FR-7.14 (v5.31).
- Classes/seams: `docs/class-design-job-runtime.md`.
- Data: `docs/data-model-job-runtime.md` (no schema change).
- API: `docs/api-job-runtime.md` (no contract change).
- Decisions: `docs/decisions-job-runtime.md` (D-01…D-09).
- Execution order/rollback: `docs/refactor-plan-job-runtime.md`.
