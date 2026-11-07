# Decision Register — Update-check resilience

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Locked** | 2026-11-07 |
| **Approved by** | HarsimranVirk (user, explicit: "add A+B+C, lock design and implement") |
| **Scope** | Failure handling and retry of the GitHub update check |
| **Companions** | `docs/FR-delivery.md` (v1.2), `docs/class-design-updates.md`, `docs/data-model-updates.md`, `docs/api-updates.md`, `docs/refactor-plan-updates.md` |
| **Supersedes / amends** | `decisions-delivery.md` D-03 (cache TTL scope), D-09 (auto loop retry), D-12 (update card actions); those rows stay locked as written and are narrowed here |

## Context

A Windows install reported
`Update check failed: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] … unable to get local
issuer certificate>` and kept showing it although `curl` **and** Python both returned `200`
on that machine afterwards. Cause: `_finish()` persisted every result, `_fresh()` only
checked `checked_at`, so one failed attempt at boot (Wi-Fi/VPN/captive portal not ready)
was replayed by the 10-minute auto loop for the full 6 h TTL, and the card had no retry
action. TLS trust on that machine is fine; the defect is the stale-failure replay.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | Only successful results (`update-available`, `up-to-date`, `disabled`) are written to `update_state.json`; a `failed` result is published in memory only. | Keep caching failures for the 6 h TTL (today), or cache them with a shorter TTL. | A failure describes one attempt, not the release. Replaying it hides a recovered network for up to 6 h and makes the auto loop a no-op without any visible cause. | `app/updater.py`, `tests/test_updater.py`, `docs/data-model-updates.md` | locked |
| D-02 | A `failed` row already on disk from an older version is ignored as a cache miss, not migrated or deleted. | Rewriting/deleting the file on first boot. | The file is disposable presentation state; treating the row as a miss is one condition and needs no migration, no version field, no write path. | `app/updater.py` (`_cached_check`) | locked |
| D-03 | No in-check retry/backoff loop: the 10-minute auto loop is the retry, plus the new manual action. | Three quick retries inside one `check_for_update` call. | The realistic cause (network not ready at boot) clears within seconds; the loop already covers it, and in-check retries would hold a FastAPI worker thread and complicate the "one attempt = one result" model. | `app/updater.py`, `AdminService._auto_update_loop` | locked |
| D-04 | The update card renders **Check again** only in the `failed` state; it forces `POST /api/updates/checks` through a new `useCheckUpdate` mutation that patches the `['updates']` cache. | Show it in every state, add a global refresh button, or rely on the 10 s poll. | `failed` is the only state the operator cannot leave by waiting; the poll already refreshes the other states, and a check never installs anything so it must not be gated on the job queue. | `frontend/src/components/UpdateCard.tsx`, `HomePage.tsx`, `queries.ts`, `UpdateCard.test.tsx` | locked |
| D-05 | `error` carries one operator-readable sentence; `detail` keeps the raw exception text. | Raw `str(exc)` in both fields (today), or a structured code+params object. | The card prints `error` verbatim, and OpenSSL text is unactionable at a glance; `detail` preserves diagnosability without changing the six-field payload or the TS types. | `app/updater.py` (`_reason`, `_failed`), `docs/api-updates.md` | locked |
| D-06 | TLS verification stays mandatory: no unverified context, no `SF_UPDATE_INSECURE`, no new `certifi` dependency in this change. | Skip certificate verification for GitHub, or add certifi + `SF_CA_BUNDLE` now. | The incident is the stale-failure cache, not trust; this machine verifies correctly. Skipping verification would void the digest guard (it travels over the same channel) for an app holding a live Salesforce session; certifi/`SF_CA_BUNDLE` is a separate, later change if a machine shows a real store gap. | `app/updater.py` (unchanged TLS path), AGENTS.md updater guards | locked |

## Consequences

- A failed check is retried by the auto loop on its next 10-minute tick and instantly by
  **Check again**; the UI never shows a failure older than the last attempt.
- `update_state.json` no longer contains `failed` rows; a stale one is harmless.
- The card's failure line becomes a sentence; support still gets the raw text from
  `detail`.
- No dependency, endpoint, schema, or TypeScript change.
- A genuine certificate/root-store problem still fails, loudly, with a message that says
  what to check — it is no longer cached.

## Open items

None. `certifi` + `SF_CA_BUNDLE` remain explicitly out of scope (D-06) and would need
their own register entry if a machine proves to have a stale root store.
