# Refactor Plan — LMS 2.0 CL contract approval gate

| | |
|---|---|
| **Status** | Locked; ready to build |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Feature** | LMS 2.0 CL contract approval gate (`deviations_z02`) |
| **Requirement** | `docs/FR-deviations.md` FR-6.17 (v5.29) |
| **Decisions** | `docs/decisions-lms2-approval.md` (v2, LOCKED 2026-11-06) D-01…D-10 |
| **Companions** | `docs/class-design-deviations.md` §7.5.1 (v4.12), `docs/data-model-deviations.md` §1.4 (v4.1), `docs/api-deviations.md` §5 (v2.13) |

This is the execution order for FR-6.17. It touches one adapter and one test module;
there is no schema, API, configuration or frontend change.

## Phases

### Phase 1 — Pure approval-state helpers

**Files:** `app/workflows/deviations_z02/adapters/lms2.py`, `tests/test_lms2.py`

1. Add `ApprovalAction` (`PROCEED`, `APPROVE`, `REFUSE`) and two pure helpers:
   - `approval_status(texts: Sequence[str]) -> str | None` — pick the approval-state pill
     out of the page's status pills, ignoring disbursal/date pills.
   - `approval_action(status_text: str | None, can_approve: bool) -> ApprovalAction` —
     map the state to proceed / approve / refuse.
2. Unit-test approved, pending, rejected, missing status, missing approve control,
   case/whitespace variants and multi-pill selection.

**Satisfies:** FR-6.17, D-02, D-04, D-10.

**Exit:** `python -m unittest tests.test_lms2` passes.

### Phase 2 — Adapter integration

**File:** `app/workflows/deviations_z02/adapters/lms2.py`

1. Add `_approval_state(page)` — read every `span.pill-status` and whether
   `button.approval-btn-approve` is visible.
2. Add `_ensure_approved(page) -> bool`:
   - `PROCEED` → true without clicking;
   - `REFUSE` → false, warning logged, nothing opened;
   - `APPROVE` → click the approve control, then the modal's `✓ Confirm Approval`
     button, then poll `_is_approved()` until the approved state is visible.
3. Call `_ensure_approved` at the top of `write()`. On false, return `UNKNOWN` for every
   target so the existing pipeline parks the item in `needs_review`.
4. Keep the existing modification open → fill → verify → Save Changes → read-back flow
   exactly as it is.

**Satisfies:** FR-6.17, D-01, D-03, D-05, D-07, D-08, D-09.

**Exit:** unit tests, `ruff`, `mypy --strict` pass.

### Phase 3 — Docs, guide and live verification

**Files:** `docs/guide-lms2-approval.md`, `docs/README.md`

1. Write the short operator guide (what it does, how to run, state, five failure modes,
   design pointers).
2. Move the ledger row to `building` when Phase 2 lands and `review` after the live
   submit; record the walkthrough after the discussion.
3. Live submit on a contract that reports **Pending Approval**:
   - approve is clicked once, the status shows approved, the modification saves, and the
     read-back equals the intended values;
   - a second submit on the now-approved contract does not click Approve again;
   - a **Rejected** contract (when one is available) fails to `needs_review` without
     opening the modification form.
4. The live result fixes the exact post-approval DOM assumptions if they differ from the
   design; a mismatch is a design amendment, not a silent code change.

**Satisfies:** FR-6.17, D-03, D-10, and the Phase C gate.

## Cutover

- Code ships with the next backend restart. No migration, no config flag, no data
  backfill.
- Behaviour begins on the next `SUBMIT` job whose targets include the LMS 2.0 CL
  contract. Jobs already running on the old code finish unchanged.
- An already-approved contract is a no-op for the gate; existing items keep working.

## Rollback

- Revert `app/workflows/deviations_z02/adapters/lms2.py` and the new tests. There is no
  persisted local state to clean up.
- **Approval cannot be rolled back by the app.** Any contract approved before the revert
  stays approved in Salesforce; this is stated in the guide and is the expected business
  outcome, not a bug.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The post-approval page does not show a literal **Approved** pill | `_ensure_approved` polls the same state reader; an unrecognised state refuses the write and the live test identifies the exact text for an amendment |
| Approve opens a confirmation dialog we do not recognise | Native dialogs are accepted one-shot; visible dialog containers are searched for an Approve/Confirm/Yes/OK button; if none is found, the post-click poll fails safe |
| Approval succeeds but the field write fails | Contract stays approved (D-05); the item is `needs_review` with existing per-field truth; no rollback attempted |
| A rejected contract is silently treated as pending | `approval_status` checks rejected before pending and `approval_action` refuses it (D-07) |
| The pre-read returns `None` while pending | Audit-only (D-09); the post-write read-back is the verification gate |
| A future page variant hides both the pill and the bar when approved | Fail-safe refusal; the live test decides whether this needs an amendment |

## Verification gate

- `python -m unittest discover -s tests`
- `ruff check app/ frontend/`
- `mypy --strict app tests`
- `npm --prefix frontend run typecheck`
- Live submit trace (Phase 3)
