# Decision Register — Final action (Implement)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v2 |
| **Date** | 2026-11-05 |
| **Locked** | 2026-11-05 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | The `execute` phase of `DeviationsZ02Submission` |
| **Companions** | `docs/FR-deviations.md` (v5.24), `docs/class-design-deviations.md` (v4.8), `docs/data-model-deviations.md` (v3.7), `docs/api-deviations.md` (v2.9) |

This register fills the one unimplemented phase of the Z02 submission pipeline. Until now
the pipeline ran apply → validate and returned `VALIDATED`; `final_action=True` raised a
reviewable failure because O-2 (the confirm label) was open. The live UI answers that
question: there is no modal, and the action is a plain button on the deviation record.

## Context

- The deviation record page shows an **Implemented** checkbox (`Implemented__c`): ticked
  means already implemented, checkered/empty means not.
- The same page has a plain button `button[name="Consumer_Loan_Deviation__c.Implemented"]`
  labelled **Implemented**. No confirmation dialog.
- `work_items` already has `execute_attempted_at` / `execute_confirmed_at`, and
  `ClosureResolver` already attributes closures from them.
- The lifecycle already allows `VALIDATING → EXECUTING`, but a live job lease forbids
  writing `COMPLETED`/`CLOSED` from inside the job.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | The final action runs on the **deviation record page**, opened from `work_items.record_url`. | The opportunity page (wrong per the live UI), or a new `deviation` ref kind. | The button and the flag live on the deviation record; the record URL is already stored on the item, so no new ref or extraction work is needed. | `app/workflows/deviations_z02/submission.py`, `adapters/deviation_record.py` | locked |
| D-02 | Implemented state is read as checked when `lightning-input:has([data-name="Implemented__c"])` has a `checked` attribute **or** contains a `utility:check` icon. | Toast text, button label, or list absence. | Those are transient or indirect; the checkbox is the same field the operator reads, and two signals make the check tolerant of LWC attribute quirks. | `adapters/deviation_record.py` | locked |
| D-03 | The action is one click on `button[name="Consumer_Loan_Deviation__c.Implemented"]` (fallback: exact text “Implemented”), with **no modal**. | Looking for a confirm dialog (O-2 assumed one), or a JS click. | The live page has no dialog; the `name` attribute is the stable selector. | `adapters/deviation_record.py` | locked |
| D-04 | Confirmation is the checkbox turning checked within the request timeout; no tick means failure. | Toast, button disappearance, or list absence. | FR-6.7 requires page state; the tick is the exact state that means implemented. | `submission.py`, `adapters/deviation_record.py` | locked |
| D-05 | A checkbox already ticked before the click returns `ALREADY_CLOSED`: no click, no execute timestamps; the next valid refresh closes it `CLOSED`/`external`/`already_implemented`. | `COMPLETED`/`system` (claims we implemented it), or writing `CLOSED` mid-job. | The user chose external attribution; a live lease forbids a job writing a closure status, and FR-6.6 already defines the external/`already_implemented` outcome. | `submission.py` | locked |
| D-06 | `mark_execute_attempted` is written immediately before the click; `mark_execute_confirmed` only after the tick is observed. | Writing “confirmed” optimistically. | A crash between click and observation must leave `implement_unconfirmed` attribution (FR-6.12), never a false success. | `submission.py` | locked |
| D-07 | The `final_action` flag and `_EXECUTE_MESSAGE` are removed; the pipeline always implements, with no kill switch. | An env flag restoring validate-only. | The user asked for the completed pipeline unconditionally; a flag would leave a second, untested code path. | `submission.py`, `__init__.py`, `tools/smoke_submit.py`, tests | locked |
| D-08 | No new UI confirmation; “Accept & submit” still enqueues directly. | A per-submission “this will implement” dialog. | The user chose fast submissions; the deck already requires an explicit Accept. | none (frontend unchanged) | locked |
| D-09 | After a confirmed click the item stays `EXECUTING` until the list watcher sees the deviation disappear; the closure resolver then writes `COMPLETED`/`system`. | Writing `COMPLETED` from the pipeline. | `WorkItemRepository` refuses closure statuses while a live job lease exists (FR-6.11); the existing closure path is the only safe writer. | `submission.py` | locked |

## Consequences

- A submit now changes Salesforce irreversibly: apply, validate, then Implement.
- An already-implemented deviation is closed externally on the next refresh, not marked
  as our success.
- If the click cannot be confirmed, the item goes to `needs_review`, the job fails, and
  `execute_attempted_at` remains so a later disappearance is attributed
  `implement_unconfirmed`.
- Confirmed items disappear from the deck immediately (`EXECUTING` is not a deck status)
  and reach `Implemented` after the next valid list refresh, not instantly.
- Live verification is required because no unit test can drive the real LWC; this is a
  destructive action, so it uses one real deviation chosen by the operator.

## Open items at lock time

- None. Modal (no), page (deviation), already-ticked semantics (external), flag (none),
  UI confirmation (no) and live testing (now) were answered by the user on 2026-11-05.
