# Data Model — Job Runtime (bounded waits, detailed logs, lease recovery)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Locked** | 2026-11-07 |
| **Approved by** | HarsimranVirk (user) |
| **Companions** | `docs/FR-deviations.md` (v5.31, FR-7.2/7.12/7.13/7.14), `docs/class-design-job-runtime.md`, `docs/api-job-runtime.md`, `docs/decisions-job-runtime.md` |

## 1. Summary

**No schema change.** There is no migration, no new table, no new column and no new
index. The feature uses the existing `jobs` and `job_logs` rows, which already carry
everything it needs.

## 2. Store ownership

| State | Store | Owner |
|---|---|---|
| Job lifecycle, attempts, lease, error | SQLite `jobs` | `JobRepository` (`app/core/repo/jobs.py`) |
| Job log lines | SQLite `job_logs` | `JobRepository.log()`, called by `RepositoryLogger` and the worker |
| Wait budgets / step timers | Process memory | `Deadline` in `app/utils/dom.py` — one per wait call, never persisted |
| Adapter step context | Process memory | Adapter method arguments (`log`) — never persisted except as log lines |

There is still no authoritative in-process queue. A restart loses only the current
`Deadline` objects; the job row and its lease are the recovery source of truth.

## 3. `jobs` — existing columns used

| Column | Type | Semantics in this feature |
|---|---|---|
| `id` | INTEGER PK | Unchanged; the log subject. |
| `status` | TEXT enum | `running` rows are the only ones stale recovery can fail. `blocked_auth` and `queued` are never expired by this change. |
| `attempts` | INTEGER | Incremented by `claim()`. Now also the stale-recovery cap: a running row is requeued while `attempts < MAX_JOB_ATTEMPTS`; at or above it, the row becomes `failed`. |
| `lease_owner` | TEXT NULL | Cleared in both stale branches. |
| `lease_expires_at` | TEXT ISO NULL | The stale boundary. NULL counts as expired, as before. |
| `started_at` | TEXT ISO NULL | Set on the first claim; not reset by a requeue. Duration remains derived. |
| `finished_at` | TEXT ISO NULL | Set by the new stale `failed` branch; it was previously left NULL on requeue (requeued rows keep it NULL). |
| `error` | TEXT NULL | New fixed strings below; no length or format change. |

### 3.1 Stale-recovery outcomes

| Condition | New status | `error` | `finished_at` |
|---|---|---|---|
| lease expired, `attempts >= 2` | `failed` | `lease expired; max attempts reached` | set |
| lease expired, `attempts < 2` | `queued` | `lease expired; requeued` | unchanged (NULL) |

`MAX_JOB_ATTEMPTS = 2` is defined once in `app/core/status.py` and used by both the
worker's retry policy and the dispatcher's stale sweep. It is not configurable in this
change; a future setting can replace the constant without a schema change.

### 3.2 Attempt timeline (normal hang/crash)

1. first `claim()` → `attempts = 1`, `running`.
2. lease expires (process killed or heartbeat lost) → `requeue_stale()` sees `1 < 2` →
   `queued`, error `lease expired; requeued`.
3. second `claim()` → `attempts = 2`, `running`.
4. lease expires again → `requeue_stale()` sees `2 >= 2` → `failed`, error
   `lease expired; max attempts reached`.

A job that finishes normally never reaches step 4. A job parked as `blocked_auth`
keeps its attempts and is resumed by a new claim after login; it is not failed by stale
recovery while parked.

## 4. `job_logs` — content only

No column changes. This feature changes *what* is written, not the shape:

- lines remain `job_id`, monotonically increasing `seq`, `line`, `at` (UTC ISO);
- the pipeline and adapters add one line per object/field/step, so a stuck job's last
  line identifies the exact operation;
- the existing 24-hour retention purge (`PurgeRepository.current`) owns these rows
  unchanged; no new retention rule.

### 4.1 Log line grammar

```
<verb>: <object>[: <field> [<section>]][: <step or value>]
<verb> ∈ {discover, precheck, readback, read, apply, execute, phase, validated}
<object> ∈ {deviation, opportunity, cl_contract, collateral,
            lms2_cl_contract, lms2_collateral}
```

Examples:

```
discover: opportunity: product type='Home Loan (Resale)'
precheck: reading cl_contract (3 target(s)): Loan Amount [Contract], Term [Contract], Financed Amount [Funding]
read: cl_contract: Loan Amount [Contract]='8,00,000.00'
apply: cl_contract: Term [Contract]: filled '120'
apply: cl_contract: Term [Contract]: saved
readback: reading cl_contract (3 target(s)): …
validated: loan_amount
phase: executing
execute: deviation: Implemented tick absent; clicking
execute: deviation: tick confirmed
```

The grammar is documentation, not a parsed contract: the UI shows the raw lines, and
no code filters on them.

## 5. Retention and migration

- Retention: unchanged. Current purge (24 h) deletes terminal jobs and their logs;
  the `sync_runs` ring is untouched.
- Migration: none. `PRAGMA user_version` and `app/db/schema.py` are unchanged.
- Existing rows: their `attempts`, `error` and status values remain valid. A row that
  is already `running` with `attempts >= 2` will be failed on the next stale sweep
  after deployment, which is the intended one-shot cleanup.
