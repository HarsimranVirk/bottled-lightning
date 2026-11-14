# Guide — LMS2 Contract Approval workflow

| | |
|---|---|
| **Status** | Built; live approval pending |
| **Version** | v1 |
| **Date** | 2026-11-14 |
| **Workflow** | `lms2_approval` (`/api/lms2-approvals`, `/lms2-approvals`) |
| **Reuses** | `docs/decisions-lms2-approval.md` D-05/D-07 and the approval gate in FR-6.17 |

## What it does, in operator language

This workflow is for approving LMS 2.0 CL contracts that are sitting in **Pending
Approval**. There is no list view and nothing to review: the operator supplies the
contract links and the app approves them automatically.

- A link becomes one item and one `SUBMIT` job immediately.
- The job opens the contract page and reads the approval bar.
- **Pending Approval** — clicks **Approve**, confirms the **Approve Loan** modal, waits
  for the page to show the approved state.
- **Already approved** — no click; the item completes.
- **Rejected**, unreadable, or unconfirmed — nothing is approved; the item goes to
  `needs_review` with a reason.

Approval is a real Salesforce action and is never rolled back. A retry on an
already-approved contract does not click Approve again.

## How to use it

1. Open the **LMS2 Approvals** tab, or follow the link on the Home page.
2. Paste one link or loan ID per line. Both shapes are accepted:
   - `https://hffc.lightning.force.com/lightning/n/CL_Contract_Detail?c__loanId=…`
   - the bare `c__loanId` value
3. Press **Queue approvals**. Each accepted line is queued immediately; no further
   action is needed.
4. Watch the **Queue** table. A failed row stays in `needs_review` with its reason.
5. Re-paste a failed link to retry it. Re-pasting a completed link is a no-op.

The **History** tab is the durable audit: one row per contract with its request time,
current status, reason and contract link. It survives the 24-hour current-data purge.

## Input rules

- Links must point at the configured Salesforce org. The Lightning host and its
  `my.salesforce.com` counterpart are accepted; any other host is rejected.
- A full link must carry `c__loanId`. The app stores the canonical detail URL even when
  the pasted link had extra query parameters or a different page path.
- A bare loan ID may not contain spaces.
- The loan ID is the item key, so the same contract cannot create two items.

## Queue and audit behaviour

| Situation | Result |
|---|---|
| New link | Item created, link stored, `SUBMIT` job queued, history snapshot written |
| Same link while a job is active | Skipped; the active job is left alone |
| Same link after completion | Skipped; the completed item stays in the audit |
| Same link after `needs_review` | Re-queued; the failure reason is cleared for the new attempt |
| Empty paste | `422`, nothing is stored |
| Invalid line | Reported in the response; other valid lines in the same paste are still queued |

The live queue shows every item, including completed ones; use its status filter to
narrow to active or failed work. The History table is newest request first and has
contract, requested-date and status filters.

## Audit retention

- **History** rows live in the existing snapshot store and are kept by the 90-day
  historical purge. One row per contract; a retry updates it rather than adding a row.
- **Per-attempt detail** (job status, phase, log lines) stays in the Jobs tab and its
  tables, which the 24-hour current-data purge removes.

## Configuration and state

- No new environment variables and no new config flag.
- `SF_HEADLESS=0` shows the live browser; the default headless run behaves identically.
- The network-profile timeouts bound each approval job.
- No new database tables, columns or migrations. Items, refs, jobs, logs and snapshots
  use the existing workflow-scoped tables.
- There is no list watcher, no extraction job and no reconciliation for this workflow.

## Endpoints

- `POST /api/lms2-approvals` — body `{"links": ["…"]}`; returns queued/skipped counts and
  per-line rejections (`202`).
- `GET /api/lms2-approvals` — live queue items.
- `GET /api/lms2-approvals/history` — durable audit snapshots.
- `GET /api/lms2-approvals/{key}` — one item with its stored link.
- `GET /api/jobs`, `GET /api/jobs/{id}/logs` — queue and per-attempt detail.

## Five likely failure modes

| Symptom | Cause | What to do |
|---|---|---|
| Row lands in `needs_review`, reason says the contract did not reach an approved state | Contract is **Rejected**, the approval bar is unreadable, or the confirm modal did not complete | Open the contract in Salesforce and resolve the approval/rejection; re-paste the link to retry |
| Row lands in `needs_review` after the click | The **Approve Loan** modal was not confirmed, or the page did not reach the approved state within the timeout | If the contract is approved in Salesforce, re-paste the link; the retry skips the click |
| Link rejected: "not on the Salesforce org" | Pasted a link from another org or a non-Salesforce page | Copy the contract link from the configured org |
| Link rejected: "the link has no c__loanId" | Pasted a Salesforce page that is not a contract detail page | Use the LMS 2.0 contract page URL or the bare loan ID |
| Item stays in `submitting`/`applying` | The job is queued behind other work, or the browser is paused for a manual login | Check the Jobs tab and the session banner; the queue resumes after login |

## Where the design is written down

- Approval page interaction and the one-way side effect:
  `docs/decisions-lms2-approval.md` (D-05, D-07) and `docs/FR-deviations.md` FR-6.17.
- Workflow wiring: `app/workflows/lms2_approval/`.
- Manual intake and list-less registration: `app/core/workflow.py`.
- Audit snapshots: `app/core/repo/approved_history.py`.
