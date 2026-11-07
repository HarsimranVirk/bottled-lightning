# Guide — Update-check resilience

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Feature** | Failed update checks retry instead of sticking for hours |
| **Design** | `docs/decisions-updates.md` (v1, LOCKED), `docs/FR-delivery.md` (v1.2) FR-2.2/2.5/2.6/4.5, `docs/class-design-updates.md`, `docs/data-model-updates.md`, `docs/api-updates.md` |

## What it does

A failed update check is now a **one-off event**, not a six-hour fact.

Before: one failed attempt (usually at boot, while Wi-Fi, a VPN or a captive portal was
still settling) was written to `update_state.json` and replayed for six hours. The auto
loop kept "re-checking" from the cache without touching GitHub, and the home page had no
retry button — so the error survived long after the network was fine. That is exactly the
Windows report: `Update check failed: <urlopen error … certificate verify failed …>`,
while `curl` and Python both reached GitHub.

Now:

- Only successful checks (`update-available`, `up-to-date`, `disabled`) are cached.
- A failure shows immediately with a plain-language line, and the auto loop really retries
  at its next tick (every 10 minutes).
- The home page shows **Check again** in the failed state, which forces a check at once.
- A stale `failed` row written by an older version is ignored.

TLS verification is unchanged and still mandatory — nothing was loosened.

## How to use it

Operator flow:

1. Home → the Version card shows either the update state or
   `Update check failed: <sentence>`.
2. If it failed, fix the obvious cause if there is one (connect the VPN, finish the Wi-Fi
   login) and click **Check again**.
3. A successful check replaces the message; if a newer release exists the card switches to
   **Install update**.

No button is needed in any other state: `up-to-date`, `update-available`, `installing`
refresh through the existing 10-second status poll.

Equivalent calls:

```bash
curl -s http://127.0.0.1:8765/api/updates          # last result, no network
curl -s -X POST http://127.0.0.1:8765/api/updates/checks   # force a real check
curl -s -X POST http://127.0.0.1:8765/api/updates/installations
```

## Configuration and state

| Thing | Where |
|---|---|
| Cache of **successful** checks | `<data dir>/update_state.json` (6 h TTL, `SF_UPDATE_CHECK_HOURS`) |
| Live status (what `GET /api/updates` returns) | `app/updater.py::_state`, in memory |
| Installed wheels | `<data dir>/updates/` (transient) |
| Auto-check cadence | 20 s after boot, then every 10 minutes (`AdminService._auto_update_loop`) |
| Database | untouched — no table, no migration |

## Five likely failure modes

| Symptom | Meaning | What to do |
|---|---|---|
| `couldn't verify GitHub's certificate — check the network, VPN or proxy, then try again` | The TLS chain could not be rooted: network not ready, captive portal, VPN, or an inspecting proxy with a private root. | Join the network/VPN properly and press **Check again**. A machine-wide stale root store or a corporate proxy needs its own fix (install the root / a `certifi`+`SF_CA_BUNDLE` change); do **not** disable verification. |
| `couldn't reach api.github.com — check the network and try again` | DNS failed. | Check DNS/VPN; retry. |
| `timed out contacting GitHub` | Firewall silently drops `api.github.com`. | Check the firewall/proxy allow-list; retry. |
| `GitHub returned HTTP 5xx` | GitHub is unhealthy or a proxy is interfering. | Retry later; the app keeps running. |
| `missing wheel asset` / `url must be a github https url` | The release itself is malformed or not GitHub-hosted. | Do not install; fix the release. The guard is intentional. |

The card shows the sentence; `GET /api/updates` also returns `detail` with the raw
`URLError`/OpenSSL text when you need to quote it in a bug report.

## Where the design lives

- `docs/decisions-updates.md` — D-01…D-06 and the rejected alternatives.
- `docs/FR-delivery.md` (v1.2) §3, §5, §9 — requirements, edge cases, acceptance criteria.
- `docs/class-design-updates.md` — publish/persist seam, `_cached_check`, `_reason`.
- `docs/data-model-updates.md` — what `update_state.json` may and may not contain.
- `docs/api-updates.md` — endpoint behaviour and payload examples.
- `docs/refactor-plan-updates.md` — slices, cutover, rollback.
