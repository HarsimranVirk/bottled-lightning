# Decision Register — LMS 2.0 CL contract approval gate

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v2 |
| **Date** | 2026-11-06 |
| **Locked** | 2026-11-06 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | The approval precondition for modifying the LMS 2.0 CL contract in `deviations_z02` |
| **Companions** | `docs/FR-deviations.md` (v5.29), `docs/class-design-deviations.md` (v4.12), `docs/data-model-deviations.md` (v4.1), `docs/api-deviations.md` (v2.13) |

## Context

The LMS 2.0 CL contract detail page (`/lightning/n/CL_Contract_Detail?c__loanId=…`)
renders a custom `c-cl-contract-detail` LWC. Its shadow root contains a status pill
(`span.pill-status`) and an approval bar (`div.approval-bar`) with **Approve** and
**Reject** controls. On the investigated contract the pill read **Pending Approval** and
both controls were enabled.

The current `Lms2ClContractAdapter.write()` opens **LOAN QUICK ACTIONS → Contract
Modification** and saves the Loan amount / Tenure cards without checking that state. When
the contract is still pending approval, Salesforce rejects the save; the adapter reports
the targets as rejected and the deviation lands in `needs_review` with a generic "writes
not accepted" reason. The fix is to make approval an explicit precondition of that write.

This register records the decisions needed for that fix, and only that.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | The approval gate lives inside `Lms2ClContractAdapter.write()`, immediately before it opens Contract Modification. | Add a new `ensure_ready`/`prepare` stage to the `ObjectAdapter` Protocol and call it from `DeviationsZ02Submission`. | Only one adapter has an approval bar; the contract page is already open and owned by `write()`, so a Protocol change would ripple through the registry, submission, tests and class design for a single object. The user chose this option explicitly. | `app/workflows/deviations_z02/adapters/lms2.py` | locked |
| D-02 | The approval state is read from the page's status pill (`span.pill-status`), with the approval bar's presence as the fallback signal; only a pending state triggers an approval click. | Infer the state from the LMS related-list row cell, or always click Approve whenever the bar exists. | The related list can show several contracts and a stale cell; clicking Approve blindly would mishandle Rejected or unknown states instead of refusing the write. | `app/workflows/deviations_z02/adapters/lms2.py` | locked |
| D-03 | A pending contract is approved by clicking `button.approval-btn-approve` (role name **Approve**), accepting an optional confirmation dialog, and polling until the page confirms the approved state before the modification starts. | Fire-and-forget the click and continue, or wait a fixed number of seconds. | The page is asynchronous; an unconfirmed approval leads straight back to a rejected Save, while a fixed sleep is flaky and slow. | `app/workflows/deviations_z02/adapters/lms2.py` | locked |
| D-04 | Approved contracts proceed unchanged; Rejected, unreadable, or unconfirmed states do not open the modification form, and every target returns `UNKNOWN`/`REJECTED`. | Attempt the write anyway, or retry approval in a loop. | Writing anyway is the current silent failure; a retry loop would hammer a business action with no evidence that a retry can help. The pipeline already turns a non-`SAVED` outcome into `needs_review`. | `app/workflows/deviations_z02/adapters/lms2.py`, `tests/test_lms2.py` | locked |
| D-05 | Approval is a one-way side effect: it is not rolled back if the later field write fails, and a retry against an already-approved contract does not click Approve again. | Record "we approved this" and try to reverse it, or re-approve on every attempt. | The page exposes no recall/un-approve control in this flow, and undoing a business approval is not the adapter's decision; retrying on an approved contract is a no-op by definition. | `app/workflows/deviations_z02/adapters/lms2.py`, `docs/FR-deviations.md` FR-6.17 | locked |
| D-06 | No new persisted state: no approval table, column, event, API endpoint, payload field or TypeScript type; the contract's SF status plus the existing submission job log and per-field truth are the record. | Add a dedicated `lms2_approved` event/table and expose it through the API. | Salesforce is the authority for the approval; a local mirror would need retention, an API reader and reconciliation, and none exists today. | `docs/data-model-deviations.md` §1.4, `docs/api-deviations.md` §5 | locked |
| D-07 | A **Rejected** contract fails the submission to `needs_review`; the system does not resubmit or re-approve it automatically. | Automatically resubmit the contract or click Approve on a rejected contract. | The rejection is an operator/business decision; the adapter cannot know why it happened, and silently overriding it is worse than a reviewable failure. Confirmed by the user. | `app/workflows/deviations_z02/adapters/lms2.py`, `docs/FR-deviations.md` FR-6.17 | locked |
| D-08 | Only the LMS 2.0 CL contract is gated; the regular CL contract, collateral, LMS 2.0 collateral and Opportunity keep their current write flow. | Add a generic approval gate to every adapter. | The other pages have no approval bar; a generic gate would add dead state and tests to five adapters for one real case. | `app/workflows/deviations_z02/adapters/lms2.py` | locked |
| D-09 | The pre-write `read()` remains before approval and may return `None` on a pending contract; it is audit/idempotency data only and never blocks the write. | Move approval into `read()` or before the pre-read so the audit always shows values. | `read()` is also the dry-run/preview path and must stay read-only; the pre-read is deliberately not a gate (FR-6.2), and the post-write read-back is the real verification. | `app/workflows/deviations_z02/adapters/lms2.py` | locked |
| D-10 | The state-to-action mapping is a pure function covered by unit tests; the browser interaction is verified by a live submit, not by a Playwright test in the suite. | Add a browser integration test for the approval click. | The project's tests are network- and browser-free by rule, and the real page lives only in the host-locked org; the live submit is the only faithful check. | `tests/test_lms2.py`, live submit | locked |

## What stays the same

- `ObjectAdapter`, `AdapterRegistry`, `DeviationsZ02Submission` and `WriteOutcome` are
  unchanged; the pipeline still decides status and retries.
- The existing write flow — open modification, clear/fill each card, verify the widget,
  Save Changes, confirm the form closed — is unchanged after approval.
- The pre-write audit, idempotency check, post-write read-back and the `needs_review`
  failure path keep their current semantics (FR-6.2/6.4/6.9/6.15).
- Discovery, extraction, refs, jobs, logs, retention, the HTTP surface and the frontend
  types are untouched.
- All other object adapters behave exactly as before.

## Amendments

None. Amendments are appended here with a date and the files/behaviour they invalidate;
locked rows are never edited in place.
