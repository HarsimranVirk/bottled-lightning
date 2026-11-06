# Decision Register — Loan Deviations (watcher recovery)

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v2 |
| **Date** | 2026-11-06 |
| **Locked** | 2026-11-06 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | Watcher page lifecycle, refresh retry policy, manual-refresh refusal |
| **Companions** | `docs/FR-deviations.md` (v5.25), `docs/class-design-deviations.md` (v4.9), `docs/data-model-deviations.md` (v3.8), `docs/api-deviations.md` (v2.10) |

## Context

With an expired session at start-up, `ListWatcher.run_forever()` called
`WorkflowListSource.open()` before its retry loop. `SessionProvider.ensure()` raised
`SessionExpired`, the exception escaped, and the watcher task ended permanently. A later
manual login reloaded the cookies and resumed the auth gate, but nothing ever re-opened the
page, so every refresh — automatic or manual — hit
`RuntimeError: WorkflowListSource.sample() before open()`. `POST /api/syncs` still answered
`202`, so the UI showed a refresh that could never happen while the failure existed only in
the server console.

This register records the decisions needed to fix that, and only that. Earlier deviations
decisions live in the four design documents; they are not retro-numbered here, and nothing
in this register restates them.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | The list page is owned by the refresh cycle: a cycle opens it when it is closed, and `run_forever()` no longer opens anything before its loop. | Keep `open()` before the loop and restart the watcher task from `AdminService.login()`. | The current shape is what dies on an expired session; restarting a background task from a login handler splits lifecycle ownership between `main.py` and the API and risks two `run_forever` tasks after repeated logins. | `app/pipeline/watcher.py`, `app/main.py` | locked |
| D-02 | `ListWatcher.refresh_once()` is the single entry point and calls `SampleSource.ensure_open()` before sampling, with `open()` idempotent while the page is open. | Let `request_sync()` open the source itself, or keep `sample()` raising when closed. | `POST /api/syncs` must work before the first background cycle; one idempotent open makes both callers correct without duplicating lifecycle rules. | `app/pipeline/watcher.py`, `app/api/services.py` | locked |
| D-03 | An `asyncio.Lock` on `ListWatcher` covers ensure-open **and** sample, so the background cycle and a manual request never open two pages or drive two reads through one page. | A lock only around `open()`; or no lock, relying on `AuthGate` alone. | Two coroutines interleave at `await` points on the single browser loop; a second `refresh()`/`read()` on the same Lightning page is a hang/race, and two pages break FR-2.1. | `app/pipeline/watcher.py` | locked |
| D-04 | `SessionExpired` closes the page, pauses `AuthGate` and returns the loop to `auth.wait()`; it never ends the watcher. | Exponential backoff, or a fixed retry counter. | A paused gate is a hard block: the next attempt requires `resume()` (a human login), so there is nothing to back off. A counter adds state for a case that is either auth-blocked or persistent. | `app/pipeline/watcher.py`, `app/jobs/auth.py` | locked |
| D-05 | Non-auth cycle failures keep today's cadence: log once, emit one `sync_failed`, then sleep the configured interval. | Backoff for all failures, or crash-and-restart supervision. | The interval already bounds retries (default 30 s) and matches current behaviour; backoff only delays recovery from transient page errors, and supervision adds a restart path that can duplicate watchers. | `app/pipeline/watcher.py` | locked |
| D-06 | `POST /api/syncs` returns `409` with `code: "login_required"` when no snapshot exists, the snapshot is flagged expired, or the gate is paused; otherwise `202` as today. | Always `202` (current); a new `session_expired` code; or blocking the request until the refresh finishes and returning its `SyncRun`. | Reusing `login_required` matches the submit endpoint's auth refusal and needs no new UI vocabulary. Blocking the request breaks the "long operations never block a request" convention and ties up a thread for a full page navigation. | `app/api/services.py`, `app/api/routes/admin.py`, `docs/api-deviations.md` | locked |
| D-07 | The UI disables **Sync now** / **Retry sync** while `session.state !== "valid"` and surfaces a `login_required` refusal as its message instead of a success. | Leave both buttons enabled and rely on the server's `409` alone. | The banner already says a login is required; an enabled button that cannot act is the dead control the operator just hit. Disabling is presentation of server state, not a client-side rule. | `frontend/src/App.tsx`, `frontend/src/components/{AppFooter,SyncBanner}.tsx`, `frontend/src/queries.ts` | locked |

## What stays the same

- The 30 s cadence, the `AuthGate` pause/resume semantics, the `SampleSource` seam's
  ownership split, and every persisted table and API payload.
- `POST /api/syncs` still returns `202` with `{"status": "requested", "workflow": …}` in the
  normal case, and still never blocks the request.
- An accepted request is still fire-and-forget: a stale snapshot that only fails on the
  attempt pauses the gate and is visible through `GET /api/sessions`, not as a retried
  request.

## Amendments

None. Amendments are appended here with a date and the files/behaviour they invalidate;
locked rows are never edited in place.
