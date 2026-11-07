# API Design — Update-check resilience

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Feature** | Update-check failure recovery |
| **Companions** | `docs/FR-delivery.md` (v1.2) FR-2.2/2.5/2.6/4.5, `docs/class-design-updates.md`, `docs/data-model-updates.md`, `docs/decisions-updates.md` |

## 1. No new or changed endpoint

The three routes keep their paths, methods, status codes and payload shape. What changes
is *which values* appear in an existing payload and how often a failure is replayed.

## 2. `GET /api/updates`

Returns the last published check/install result. Reads in-memory state only; never the
network. Unchanged shape:

```json
{
  "status": "failed",
  "updateAvailable": false,
  "detail": "URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1147)>",
  "error": "couldn't verify GitHub's certificate — check the network, VPN or proxy, then try again",
  "latest": null,
  "downloadUrl": null
}
```

| Field | Type | Meaning |
|---|---|---|
| `status` | string | `idle`, `update-available`, `up-to-date`, `disabled`, `installing`, `installed`, `failed`, `blocked`, `unknown` |
| `updateAvailable` | bool | Latest tag is newer than the running version |
| `detail` | string? | Raw exception text on failure; `ok`/`no releases`/the install reason otherwise |
| `error` | string? | Operator-readable failure sentence (was: raw exception text) |
| `latest` | string? | Release tag; `null` on failure so no stale tag is shown |
| `downloadUrl` | string? | GitHub HTTPS wheel URL; `null` on failure |

A `failed` result is published immediately but is **not** written to
`update_state.json`; the next check retries the network.

## 3. `POST /api/updates/checks`

Forces a check, bypassing the successful-result cache. Returns `200` with the same
`UpdateStatusView` shape, whether the outcome is `update-available`, `up-to-date` or
`failed`.

- Network/TLS failure: `200` + `status="failed"`; never a 5xx (the check never raises).
- Invalid/untrusted release asset: `200` + `status="failed"` with `error` naming the guard
  (`missing wheel asset`, `url must be a github https url`, …).
- Policy `off`: `200` + `status="disabled"` without touching the network.

This is the endpoint behind the new **Check again** action.

## 4. `POST /api/updates/installations`

Unchanged. `202` with the current status (`installing`), or `409`/`200` as before. A
failure during download/pip is still reported as `status="failed"` with a readable
`error` and the raw cause in `detail`.

## 5. TypeScript

`frontend/src/types.ts` is **unchanged** — no schema is regenerated. `UpdateStatus` keeps
`status`, `updateAvailable`, `detail`, `error`, `latest`, `downloadUrl`, all nullable
where they were.

## 6. Client

| Hook / component | Change |
|---|---|
| `api.checkUpdate()` | unchanged (`POST /api/updates/checks`); now actually used |
| `useCheckUpdate()` | new mutation; `onSuccess` patches `['updates']` with the response |
| `useUpdates()` | unchanged 10 s poll of `GET /api/updates` |
| `UpdateCard` | new `checking`/`onCheck` props; renders **Check again** only in `failed` |

No business logic moves into the browser: the button triggers the existing forced check and
displays whatever the server returns.
