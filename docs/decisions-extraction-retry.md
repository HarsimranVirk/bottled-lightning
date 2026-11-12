# Decision Register — Retryable Incomplete Extraction

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-12 |
| **Locked** | 2026-11-12 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | Every incomplete extraction becomes operator work, with a per-card retry |
| **Companions** | `docs/FR-deviations.md` (v5.32), `docs/class-design-deviations.md` (v4.15), `docs/data-model-deviations.md` (v4.3), `docs/api-deviations.md` (v2.15) |
| **Supersedes** | `docs/decisions-extraction-recovery.md` (v1, LOCKED 2026-11-06) |

## Context

Extraction failed silently in two ways. An adapter that found nothing returned an empty
result, so the item became `ready` with two of five links stored; an ambiguity wrote
`SKIPPED`, a terminal state with no way back except a code change. The operator could not
tell which page was missing, could not retry, and a `skipped` item was invisible in the
deck. The old register only patched the narrow case where a list row had no record link
yet.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | Every declared object kind is stored exactly once with a tri-state `found` / `absent` / `unresolved`, and a non-`found` row carries a plain one-line reason instead of a URL. | Keep `skip_reason` on the discovery plus loose booleans. | One reason per link cannot drift from the link's state, and "the list never rendered" can no longer look like "there is no collateral". | `app/core/status.py` (`RefState`), `app/core/models.py`, `app/salesforce/adapters.py`, the five adapters | locked |
| D-02 | An extraction that cannot resolve every required link writes `needs_review` with the first incomplete link's reason and returns `INCOMPLETE`; the job fails with that reason and is never requeued. | Keep `SKIPPED` as the terminal, invisible outcome. | The operator can fix a vendor page mismatch; a terminal state hides that work. Retry must be user-driven. | `app/core/status.py`, `app/workflows/deviations_z02/extraction.py`, `app/jobs/worker.py` | locked |
| D-03 | Retry is a card action backed by `POST /api/deviations/{key}/extractions`, accepted only for a `needs_review` item whose extraction is incomplete or has no marker, and refused with a code otherwise. | An automatic retry budget, or a `force` flag on the existing submit route. | A loop would hide a persistent SF problem; the operator decides when to spend another minute of browser work. | `app/api/services.py`, `app/api/routes/workflows.py` | locked |
| D-04 | The retry clears `extracted_at` and keeps stored values, proposals and the current reason. | Reuse the one-shot marker so the new job returns immediately. | Without clearing it the retry is a no-op for rows extracted before link states existed; wiping values would discard the operator's work mid-review. | `app/core/repo/work_items.py`, `app/api/services.py` | locked |
| D-05 | A row with no record link stays `present` with no job, no reason and no card; the refresh that first supplies the link queues exactly one extraction. | Record a `skipped` item with a reason so the operator sees it. | There is nothing to open and nothing the operator can do; the missing input is the link, not a review decision. | `app/pipeline/reconciler.py`, `app/workflows/deviations_z02/extraction.py` | locked |
| D-06 | "Complete" is one function, `incomplete_ref(ref_kinds, refs)`, shared by extraction, the reconciler audit and the submission preflight. | Let each caller decide with its own loop. | The three layers must never disagree about readiness; duplicating the rule is how the silent hole appeared. | `app/core/workflow.py` | locked |
| D-07 | Requiredness is declared per kind (`RefKind(kind, required)`); Z02 marks all five required. An optional kind may be `absent` but never `unresolved`. | A second `required_ref_kinds` list beside `ref_kinds`. | One declaration, one validation point, and extraction's constructor refuses a kind without a plain fallback reason. | `app/core/workflow.py`, `app/workflows/deviations_z02/__init__.py` | locked |
| D-08 | A valid refresh audits items that cannot progress: `extracting` with no active job, and `ready` with an incomplete required link set, both become `needs_review` with a plain reason. | Trust the stored status; fix legacy rows by hand. | A crashed extraction and a pre-v6 `ready` row are otherwise invisible forever. | `app/pipeline/reconciler.py`, `app/core/repo/work_items.py` (`expect=` guard) | locked |
| D-09 | Submission refuses when a required link is not usable: `409 extraction_incomplete` at the API, and the same check before the pipeline's first status change. | Let the browser step fail on the empty URL. | The card already knows which page is missing, and a refused job writes nothing and changes nothing. | `app/api/services.py`, `app/workflows/deviations_z02/submission.py` | locked |
| D-10 | The one-time v6 migration turns the legacy missing-URL skip into `present` (reason cleared) and every other `skipped` row into `needs_review`. | Leave legacy rows terminal. | Otherwise exactly the items this feature exists for stay invisible after the upgrade. | `app/db/schema.py`, `app/db/connection.py` | locked |

## What stays the same

- Extraction still runs one `EXTRACT` job per deviation, with the record → opportunity →
  parallel-objects dependency chain and the same forced `force=True` path for terminal rows.
- The job-runtime retry policy for a *job row* is untouched: `TransientBrowserError` and a
  persistence failure still get one automatic attempt, and the stale-lease sweep still
  fails a job at `MAX_JOB_ATTEMPTS`. A manual retry is a new job row with `attempts = 0`.
- `WorkItemStatus.SKIPPED` stays in the enum and in `TERMINAL_STATUSES`; only extraction
  stops writing it, because pre-v6 rows and the approved-history snapshots still contain it.
- The submission and apply/validate/implement phases, the LMS 2.0 approval gate and the
  edit audit are unchanged apart from the link preflight.
- No new table; v6 only adds two columns to each refs table.

## Amendments

| Date | Amendment |
|---|---|
| 2026-11-12 | A planned detail boolean `extraction_incomplete` was dropped during the frontend slice: `refs[].state` plus the item reason already say what is missing. The detail exposes `extractionRetryable` and `extractionJob` instead, because those cannot be derived from the refs. |
