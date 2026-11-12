# Refactor Plan — Job Runtime (bounded waits, detailed logs, lease recovery)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Locked** | 2026-11-07 |
| **Approved by** | HarsimranVirk (user) |
| **Companions** | `docs/FR-deviations.md` (v5.31, FR-7.2/7.12/7.13/7.14), `docs/class-design-job-runtime.md`, `docs/data-model-job-runtime.md`, `docs/api-job-runtime.md`, `docs/decisions-job-runtime.md` |

Execution order is mandatory. Each slice names the `D-xx` / `FR-x.y` it satisfies and
lands with its tests. If the code disagrees with a locked decision, stop and amend the
register first.

## Phase 1 — Wait budgets (D-01…D-04, FR-7.12)

1. Add `Deadline`, `bounded` and `LocatorLike` to `app/utils/dom.py`.
2. Rewrite `poll`, `click_first_visible`, `clear_and_fill`, `wait_for_rows` and
   `wait_for_text` to use the deadline and remaining-budget action timeouts.
3. Make `cl_contract._form_frame`, `_matching_labels`, `_label_cell`, `_value_cell` and
   `_saved` budget-aware; `lms2._open_lms_tab` and `_await_lms_rows` use a deadline.
4. Add `tests/test_dom.py` with a slow predicate and fake locator proving the wall-clock
   bound (no browser).

**Exit:** the cl_contract path can no longer exceed its configured budgets by more than
one bounded check; unit tests cover slow-predicate and visible-but-unclickable cases.

## Phase 2 — Log seam and detailed lines (D-05, FR-7.13)

1. Move `JobLogger` to `app/core/job_logger.py`; re-export from `app/core/workflow.py`.
2. Extend `ObjectAdapter`/`AdapterBase` `discover`/`read`/`write` with `log`.
3. Pass `log` from `DeviationsZ02Extraction` and `DeviationsZ02Submission`; add
   `precheck`/`readback`/`preview` stage labels, phase lines and `validated:` lines.
4. Add per-object/per-field step lines to all six adapters, including the final action
   (`DeviationRecordAdapter.is_implemented/implement`).
5. Update `tools/smoke_submit.py` with a print logger.
6. Extend the fake adapters in `tests/test_submission.py` and `tests/test_extraction.py`;
   add log-content assertions (precheck, apply, readback, final action).

**Exit:** a simulated hang at each step leaves a persisted line naming object, field and
step.

## Phase 3 — Heartbeat and stale recovery (D-06, D-07, D-09, FR-7.2/7.14)

1. Add `MAX_JOB_ATTEMPTS = 2` to `app/core/status.py`; use it in `Worker`.
2. Log and retry heartbeat failures in `Worker._heartbeat`.
3. Change `JobRepository.requeue_stale(max_attempts)` to fail at the cap and requeue
   below it; pass `MAX_JOB_ATTEMPTS` from `Dispatcher`.
4. Update `tests/test_repositories.py` and add heartbeat-resilience coverage in
   `tests/test_jobs.py`, plus a dispatcher assertion for the stale cap.

**Exit:** a job that loses its lease twice ends `failed` with
`lease expired; max attempts reached` and cannot resurrect on a restart; a flaky
heartbeat does not complete the job early or duplicate it.

## Phase 4 — Documentation and verification

1. Update `docs/class-design-deviations.md` snippets for the adapter seam,
   `requeue_stale` and the worker.
2. Write `docs/guide-job-runtime.md`.
3. Update `docs/README.md` ledger to `review` (live walkthrough pending).
4. Run `ruff check app/ tests/`, `mypy --strict app tests`,
   `npm --prefix frontend run typecheck` and `python -m unittest discover -s tests`.
5. No frontend source change is expected; the typecheck is a guard.

## Cutover

- No data migration. Deploy the wheel; the first idle claim loop after boot performs
  the one-shot stale sweep, so an old `running` row with `attempts >= 2` fails visibly.
- No configuration change. `MAX_JOB_ATTEMPTS` is a code constant.
- No API/UI change; operators see the new error text and log lines in the existing jobs
  screen.

## Rollback

- Revert the release to the previous wheel. The database is untouched, so there is
  nothing to undo.
- Jobs failed by the stale cap stay `failed`; re-submit the item from the review deck if
  the operator wants another run.
- Log lines written by the new version remain readable by the old version (plain text).

## Verification checklist

- [ ] `ruff check app/ tests/` clean.
- [ ] `mypy --strict app tests` clean.
- [ ] `npm --prefix frontend run typecheck` clean.
- [ ] `python -m unittest discover -s tests` green.
- [ ] Header-total cross-check not touched (no extraction selector change).
- [ ] No scratch files left behind.
