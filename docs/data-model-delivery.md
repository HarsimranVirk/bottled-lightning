# Data Model — Delivery (launchers, updates, LAN access)

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v1 |
| **Date** | 2026-11-05 |
| **Companions** | `docs/FR-delivery.md`, `docs/class-design-delivery.md`, `docs/api-delivery.md`, `docs/decisions-delivery.md` |

## 1. Database

**No change.** No table, column, index or migration is added. The SQLite schema stays v5.

## 2. Update state file

`<data_dir>/update_state.json` — presentation/check state, not domain data. Rewritten on
every check; safe to delete (the next check recreates it).

```json
{
  "status": "update-available",
  "update_available": true,
  "latest": "v0.4.0",
  "download_url": "https://github.com/…/bottled_lightning-0.4.0-py3-none-any.whl",
  "sha256": "…64 hex chars, when GitHub provides a digest…",
  "checked_at": "2026-11-05T15:30:00Z",
  "error": null,
  "detail": "ok"
}
```

| Field | Type | Meaning |
|---|---|---|
| `status` | string | `idle`, `update-available`, `up-to-date`, `disabled`, `installing`, `installed`, `failed`, `blocked` |
| `update_available` | bool | Whether the latest tag is newer than the running version |
| `latest` | string? | Release tag (`v0.4.0`) |
| `download_url` | string? | GitHub HTTPS wheel URL |
| `sha256` | string? | Lower-case hex digest parsed from the asset `digest` |
| `checked_at` | string? | UTC ISO timestamp; drives the 6 h cache TTL |
| `error` / `detail` | string? | Operator-readable reason |

There is no retention job: the file is a single row, overwritten in place.

## 3. Download cache

`<data_dir>/updates/` holds the wheel currently being installed
(`<name>-<tag>.whl`). It is transient:

- created only during an install,
- deleted in `finally` after a successful install or a failure,
- never read by any other feature,
- safe to delete manually.

No lock file is needed: `AdminService` holds an in-process install lock, and only one
process runs the app per data directory.

## 4. Settings

`Settings.host` / `Settings.port` are runtime configuration, not persisted. They mirror the
actual uvicorn bind and are only used to build the network view and the boot banner.
`SF_UPDATE_CHECK_HOURS` is an environment override for the 6 h TTL.

## 5. Launcher state

The launchers keep their virtualenv under the OS app-data directory
(`~/Library/Application Support/bottled-lightning/venv`,
`%LOCALAPPDATA%\bottled-lightning\venv`). The app never reads or writes that directory;
only pip and the launcher do.
