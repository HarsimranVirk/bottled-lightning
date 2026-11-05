# Guide — Final action (Implement)

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Feature** | The `execute` phase of the Z02 submission pipeline |
| **Design** | `docs/decisions-final-action.md` (v2, LOCKED), `docs/FR-deviations.md` FR-6.5–6.7/6.14/6.16, `docs/class-design-deviations.md` §9.3 |

## What it does

A submit now finishes the job it always described:

1. **Apply** the operator's values to the opportunity and CL contract.
2. **Validate** that every value read back.
3. **Implement** on the deviation record:
   - opens the deviation record page,
   - reads the **Implemented** checkbox (`Implemented__c`),
   - if it is already ticked, stops: the deviation is treated as implemented
     externally — no click, no claim of credit,
   - otherwise clicks the **Implemented** button and waits for the checkbox to turn
     ticked.

There is **no confirmation modal**. The tick is both the pre-check and the proof.

The item leaves the review deck as soon as the job reaches `executing`. It appears as
**Implemented** in History after the next list refresh attributes the closure
(`COMPLETED`, source `system`). An already-ticked deviation closes as `CLOSED`, source
`external`, reason `already_implemented`.

## How to use it

1. In the review deck, edit the values and press **Accept & update**. There is no extra
   confirmation — this now implements the deviation in Salesforce.
2. Watch the job in the Jobs table. A successful run logs `implement clicked` and
   `implemented`, and the job completes.
3. The card disappears from the deck. Within about one refresh cycle (30 s) the item is
   `completed` and the History row reads **Implemented**.

Nothing new to configure. The action runs unconditionally; there is no validate-only
switch.

## Configuration and where state lives

| Thing | Where |
|---|---|
| Implement button | `button[name="Consumer_Loan_Deviation__c.Implemented"]` on the deviation record |
| Implemented flag | `Implemented__c` on the deviation record (`lightning-input`) |
| Click recorded | `work_items.execute_attempted_at` |
| Tick recorded | `work_items.execute_confirmed_at` |
| Closure | `ClosureResolver` on the next valid refresh |

No schema change, no environment variable, no API payload change.

## Five most likely failure modes

1. **Job failed: “Implement clicked but the Implemented checkbox did not turn on”.**
   The click happened but the tick was not observed within the timeout. The item is in
   `needs_review` and `execute_attempted_at` is set, so a later disappearance is
   attributed `implement_unconfirmed`. Check the deviation in Salesforce; resubmit after
   fixing the cause.

2. **Job failed: “Implemented checkbox not found on the deviation record”.**
   The record layout, field permission or selector changed. The pipeline refuses to
   guess. Verify the `Implemented__c` field is visible on the record; the selector lives
   in `adapters/deviation_record.py`.

3. **Job failed: “item has no deviation record URL”.**
   The list row had no record link. Force a list refresh; the next extraction stores the
   URL.

4. **The card vanished but History still shows `Executing`.**
   Expected — the job cannot write the terminal status while it holds the lease. The
   next valid refresh closes it as `COMPLETED`. If it never does, check that the
   deviation actually left the list view.

5. **A run returns `already_closed` and no click happens.**
   The checkbox was already ticked: someone (or an earlier run) implemented it. It is
   attributed `external`/`already_implemented`, never as our success.

## Where to read more

- Decision register: `docs/decisions-final-action.md` (D-01…D-09, locked 2026-11-05).
- Requirements: `docs/FR-deviations.md` FR-6.5–6.7, FR-6.14, FR-6.16; O-2 resolved.
- Pipeline and adapter design: `docs/class-design-deviations.md` §9.3.
- Data model: `docs/data-model-deviations.md` (final-action timestamps).
- Execution order: `docs/refactor-plan-final-action.md`.
