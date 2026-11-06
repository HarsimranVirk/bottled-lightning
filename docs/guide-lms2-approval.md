# Guide — LMS 2.0 CL contract approval gate

| | |
|---|---|
| **Status** | Built; live submit pending |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Requirement** | `docs/FR-deviations.md` FR-6.17 (v5.29) |
| **Decisions** | `docs/decisions-lms2-approval.md` (v2, LOCKED 2026-11-06) D-01…D-10 |
| **Execution** | `docs/refactor-plan-lms2-approval.md` (v1) |

## What it does, in operator language

When a deviation changes the **loan amount** or **tenure**, one of the targets is the
**LMS 2.0 CL contract**. That contract must be approved before Salesforce accepts a
Contract Modification. The app now checks the contract's approval bar first:

- **Approved** — nothing extra happens; the modification is written as before.
- **Pending Approval** — the app clicks **Approve**, confirms the **Approve Loan** modal
  with **✓ Confirm Approval**, waits until the page shows the approved state, then writes
  the loan amount / tenure.
- **Rejected**, or a state the page does not expose clearly — the app writes nothing. The
  deviation moves to `needs_review` so a human can look at it.

The approval is a real Salesforce action and is **not undone** if a later field write
fails. A retry on an approved contract does not click Approve again.

## How to use it

Nothing new to click in the app. The existing flow does the work:

1. Start the app: `python -m app.main` (or the launcher). Use
   `SF_HEADLESS=0 python -m app.main` if you want to watch the browser.
2. Review a deviation whose values include the LMS 2.0 contract (loan amount or tenure)
   and choose **Accept & update**.
3. The app enqueues a `SUBMIT` job. It opens the contract page from the stored ref
   (`/lightning/n/CL_Contract_Detail?c__loanId=…`), clicks **Approve**, confirms the
   **Approve Loan** modal with **✓ Confirm Approval** when pending, then opens
   **LOAN QUICK ACTIONS → Contract Modification** and saves the cards.
4. Watch it in the **Jobs** table and the deviation's per-field truth. The job log shows
   `apply: lms2_cl_contract`; the server log shows
   `lms cl-contract is pending approval; approving before write` when the click happens.

Endpoints involved (no new ones):

- `POST /api/deviations/{key}/jobs` → `202` starts the submission.
- `GET /api/jobs/{id}` and `GET /api/jobs/{id}/logs` → job status and log lines.
- `GET /api/deviations/{key}` → the item's status and per-field `applied`/`rejected`
  truth.

Reading the approval state is the only thing the adapter does before the write; the
existing write and read-back verification are unchanged.

## Configuration and state

- No new environment variables and no new config flag. The gate is always on for the LMS
  2.0 CL contract.
- `SF_HEADLESS=0` shows the live page; the default headless run behaves identically.
- `REQUEST_TIMEOUT_MS` (60 s in `app/config.py`) bounds the wait for the approved state.
- Approval state lives in **Salesforce**, not in `data/app.db`. There is no new table,
  column, index, event or migration. Existing rows and the history store are untouched;
  the existing job log and per-field truth record the submission.

## Five likely failure modes

| Symptom | Cause | What to do |
|---|---|---|
| Item lands in `needs_review`, log says `approval refused` | The contract is **Rejected** (or its state is not readable) | Open the contract in Salesforce and resolve the approval/rejection; resubmit after it is approved |
| Item lands in `needs_review` after the approve click, log says `approval was not confirmed` | The **Approve Loan** modal was not confirmed, or the page did not reach an approved state within the timeout | If the contract is approved in SF, resubmit (the retry skips the click). If the modal was left open or the state is still pending, capture the page state for a design amendment |
| `needs_review` with `writes not accepted: lms2_cl_contract/...` and no approve line | The Approve control is not visible on this contract/page variant | Verify the page still shows `div.approval-bar` and `button.approval-btn-approve`; report the variant before changing selectors |
| Contract approved but the field save is rejected | A different validation error (amount/tenure rules, page error) | The approval stays in place; fix the Salesforce issue and resubmit. No rollback is attempted |
| Job log precheck shows `None` for the LMS 2.0 values | The contract is pending and the modification form is not readable yet; the pre-read is audit-only | Expected. The post-write read-back is the real gate; no action unless the submit also fails |

## Where the design is written down

- Requirements: `docs/FR-deviations.md` **FR-6.17** (v5.29).
- Classes and page state: `docs/class-design-deviations.md` §7.5.1 (v4.12).
- Data (no schema change): `docs/data-model-deviations.md` §1.4 (v4.1).
- API (no surface change): `docs/api-deviations.md` §5 (v2.13).
- Decisions: `docs/decisions-lms2-approval.md` D-01…D-10 (v2, LOCKED).
- Execution order: `docs/refactor-plan-lms2-approval.md` (v1).
