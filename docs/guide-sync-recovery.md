# Guide — Sync recovery (watcher page lifecycle)

| | |
|---|---|
| **Status** | Built; live walkthrough pending |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Change** | `docs/refactor-plan-deviations.md` §9 (Change C-1) |
| **Decisions** | `docs/decisions-deviations.md` (v2, LOCKED) D-01…D-07 |

## What it does, in operator language

The list refresh no longer dies when Salesforce has logged you out. If the app starts with
an expired session, the refresh waits for you to log in and then reopens its list page by
itself. **Sync now** works again without restarting the app, and if the session is known to
be expired the button is disabled and the server refuses the request instead of pretending
it started a refresh.

Before this change, an expired session at start-up ended the background refresh for the life
of the process: every **Sync now** (and every 30 s cycle) failed with
`WorkflowListSource.sample() before open()`, while the API still answered `202`.

## How to use it

Nothing new to click. The flow is:

1. Start the app: `python -m app.main` (or the launcher).
2. If the session is expired, the banner says so and **Sync now** is disabled.
3. Click **Log in** and finish the Salesforce login in the opened browser.
4. Within one refresh interval (30 s by default) the list page reopens and a valid
   `sync_run` is recorded. **Sync now** is enabled again.

Endpoints involved:

- `POST /api/syncs?workflow=deviations_z02` → `202 {"status": "requested", "workflow": …}`
  when a refresh will be attempted; `409 {"detail": {"code": "login_required", …}}` when the
  session is already known to need a login; `404` for an unknown workflow.
- `GET /api/sessions` → `state` (`none` / `valid` / `expired`) and `paused`. This is how the
  UI knows to disable the button.
- `GET /api/syncs?workflow=…` → the latest run (`valid`, `headerTotal`, `rowsRead`, …).

## Configuration and state

- `SF_RESYNC_INTERVAL_SECONDS` (default `30`) — the automatic refresh cadence, and the
  upper bound on how long a non-auth failure waits before retrying.
- `SF_DATA_DIR` — where `app.db` lives (session snapshot, items, sync runs).
- No schema change and no new tables. The open page, the "is it open" flag and the
  per-workflow lock are in-process state on the browser loop. The only rows written are the
  existing `session_events` (`auth_paused` / `auth_resumed`) and `work_item_events`
  (`sync_failed`).

## Five likely failure modes

| Symptom | Cause | What to do |
|---|---|---|
| Banner says *Session expired*, **Sync now** greyed out | No valid snapshot, or the last SF interaction found the login page | Click **Log in** and finish the browser login; the next cycle reopens the page |
| `POST /api/syncs` returns `409 login_required` | Same as above, called directly (`curl`, another client) | Log in first; `GET /api/sessions` shows the state the refusal is based on |
| **Sync now** returns `202` but nothing refreshes, and the banner flips to expired a moment later | The stored snapshot looked valid but was already dead; the attempt discovered it | Expected: the gate pauses and the banner reports it. Log in once; the request is not retried |
| `sync_failed` in the event log every ~30 s, no new `sync_run` | A non-auth page problem (timeout, detached page, list view not rendering) | Check the server log for the traceback; the cycle keeps retrying at the interval, no restart needed |
| Latest sync shows *untrusted* (header total ≠ rows) | The list page rendered a different number of rows than its own header | Not related to auth. Retry from the warning banner; if it persists, the list view itself needs checking |

## Where the design is written down

- Requirements: `docs/FR-deviations.md` FR-1.4, FR-2.1/2.2, FR-2.10–2.13, FR-9.25.
- Classes and lifecycle: `docs/class-design-deviations.md` §8.1, §11.1, invariant I16.
- API contract: `docs/api-deviations.md` §4.
- Data: `docs/data-model-deviations.md` §1.1 (no schema change).
- Decisions: `docs/decisions-deviations.md` D-01…D-07.
- Execution order: `docs/refactor-plan-deviations.md` §9.
