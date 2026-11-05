# Refactor Plan — Final action (Implement)

| | |
|---|---|
| **Status** | Ready — executing |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Depends on** | `docs/decisions-final-action.md` (v2, LOCKED 2026-11-05) |
| **Touches** | `app/workflows/deviations_z02/{submission.py,__init__.py}`, `app/workflows/deviations_z02/adapters/deviation_record.py`, `tools/smoke_submit.py`, `tests/test_submission.py`, `docs/guide-final-action.md`, `docs/README.md` |
| **Does not touch** | database schema, API payloads, frontend, extraction, purge |

## 1. Slices

### Slice 1 — adapter capability (D-01…D-04)

`DeviationRecordAdapter` gains three methods:

```python
async def open_record(self, tabs: TabProvider, record_url: str) -> Page
async def is_implemented(self, page: Page) -> bool
async def implement(self, page: Page) -> bool
```

- Field locator: `lightning-input:has([data-name="Implemented__c"])`.
- Checked if the `checked` attribute is present **or** a `utility:check` icon exists inside
  the field.
- Button: `button[name="Consumer_Loan_Deviation__c.Implemented"]`, fallback to a button
  whose exact text is `Implemented`.
- `implement` polls the checkbox until checked or the timeout; returns the observation.

### Slice 2 — pipeline (D-05…D-09)

`DeviationsZ02Submission` drops the `final_action` flag and the `_EXECUTE_MESSAGE`:

```
after read-back + still-present check:
  open deviation page from item.record_url
  ticked  → ALREADY_CLOSED (no click, no timestamps)
  else    → transition EXECUTING
            mark_execute_attempted
            click + poll tick
              ticked  → mark_execute_confirmed → emit → COMPLETED
              no tick → NEEDS_REVIEW + FAILED
```

`build_workflow` and `tools/smoke_submit.py` stop passing the flag. `VALIDATED` is no
longer returned.

### Slice 3 — Phase C artefacts

`docs/guide-final-action.md`, ledger row, live walkthrough with one real deviation.

## 2. Verification gates

```bash
source .venv/bin/activate
python -m unittest discover -s tests
mypy --strict app tests tools
uvx ruff check app/ tools/ tests/
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run
```

No schema or API change, so no OpenAPI regeneration and no migration.

## 3. Cutover

- Restart the backend. The first submit after that implements in Salesforce.
- Take a copy of `data/app.db` first if you want the pre-test job history.
- Live verification uses a deviation the operator chooses; no automated click.

## 4. Rollback

- Revert the commit and restart: the pipeline returns to validate-only because the code
  that clicked is gone.
- A deviation already implemented in Salesforce cannot be un-implemented by rollback;
  that is a manual SF action.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Wrong checkbox detected as “implemented” | Two signals (attribute or icon) and a precheck log line; live run supervised |
| Click not confirmed | Job fails, item `needs_review`, `execute_attempted_at` retained |
| Double implementation | Tick checked before every click; a retry sees the tick |
| Closure delay | Item stays `EXECUTING` until the next valid refresh (D-09), documented |
| Destructive live test | One operator-chosen deviation; no smoke automation |
