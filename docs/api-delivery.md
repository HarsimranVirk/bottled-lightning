# API Design — Delivery (launchers, updates, LAN access)

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Feature** | Delivery |
| **Companions** | `docs/FR-delivery.md`, `docs/class-design-delivery.md`, `docs/data-model-delivery.md` |

## 1. `GET /api/network`

Read-only server address information for the home page.

```json
{
  "host": "0.0.0.0",
  "port": 8765,
  "lanIp": "192.168.1.42",
  "lanUrl": "http://192.168.1.42:8765",
  "localUrl": "http://127.0.0.1:8765",
  "lanEnabled": true
}
```

| Field | Type | Meaning |
|---|---|---|
| `host` | string | Actual uvicorn bind host (`0.0.0.0` means all interfaces) |
| `port` | int | Actual bind port |
| `lanIp` | string? | Detected outbound interface address; `null` when unavailable |
| `lanUrl` | string? | `http://<lanIp>:<port>` when both host and IP allow LAN access |
| `localUrl` | string | `http://127.0.0.1:<port>` |
| `lanEnabled` | bool | `host` is not loopback **and** `lanIp` was detected |

No errors: an undetectable IP yields `lanIp: null`, `lanUrl: null`, `lanEnabled: false`.

## 2. `POST /api/updates/installations`

Start installing the pending update. Returns `202` with the current update status; the
install continues in the background and the process restarts on success.

```json
{
  "status": "installing",
  "updateAvailable": true,
  "detail": "installing v0.4.0",
  "error": null,
  "latest": "v0.4.0",
  "downloadUrl": "https://github.com/…/bottled_lightning-0.4.0-py3-none-any.whl"
}
```

Errors:

- `409` with `code="update_blocked"` when a job is queued/running/blocked, a manual login
  is in progress, the app runs from a source checkout without `SF_UPDATE_ALLOW_SOURCE=1`,
  or another install is already running. `detail.message` names the reason.
- `202` with status `up-to-date` when there is nothing to install (no error; the button is
  hidden in that state anyway).

## 3. `GET /api/updates` (unchanged shape)

Statuses now also include `installing`, `installed` and `blocked` in addition to `idle`,
`update-available`, `up-to-date`, `disabled`, `failed`. The DTO fields are unchanged.

## 4. `POST /api/updates/checks` (unchanged)

Forces a check (bypasses the 6 h cache) and returns the same shape.

## 5. TypeScript

`frontend/src/types.ts` is regenerated. The new schema is:

```ts
export interface NetworkView {
  host: string;
  port: number;
  lanIp: string | null;
  lanUrl: string | null;
  localUrl: string;
  lanEnabled: boolean;
}
```

`UpdateStatus` gains the extra status literals through the existing `string` field; no shape
change. `api.ts` exposes:

```ts
network: (): Promise<NetworkView> => request('/api/network')
installUpdate: (): Promise<UpdateStatus> =>
  request('/api/updates/installations', { method: 'POST' })
```

## 6. Query hooks

- `useNetwork()` — 10 s poll while visible (address can change with Wi-Fi/VPN), no cache
  invalidation needed.
- `useInstallUpdate()` — mutation; invalidates `updates` on success and polls while
  `status === "installing"`.
