# Class Design — Update-check resilience

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-07 |
| **Companions** | `docs/FR-delivery.md` (v1.2) FR-2.2, FR-2.5, FR-2.6, FR-4.5, AC-1…AC-6; `docs/data-model-updates.md`; `docs/api-updates.md`; `docs/decisions-updates.md` |

## 1. Problem framing

The updater's failure path treated a single failed attempt as a fact about the release:
`_finish()` stamped and persisted every result, `_fresh()` only looked at `checked_at`, and
so a `failed` row was replayed for the full 6 h TTL. The auto loop calls
`check_for_update(force=False)` every 10 minutes, so it kept returning the cached failure
without touching the network, and the card had no retry action. One botched handshake at
boot (Wi-Fi/VPN/captive portal still settling) became a six-hour error on screen.

## 2. Ownership (unchanged)

| Concern | Owner |
|---|---|
| Release lookup, version compare, cache, error wording | `app/updater.py` (module functions) |
| When checks/installs run, guards, background loop | `app/api/services.py::AdminService` |
| HTTP surface | `app/api/routes/admin.py` |
| Presentation and retry action | `frontend/src/components/UpdateCard.tsx`, `HomePage.tsx`, `queries.ts` |

No new class, Protocol or table is introduced. The change is three seams inside
`app/updater.py` plus one mutation hook and one prop pair in the frontend.

## 3. `app/updater.py`

### 3.1 Publish vs persist

Today:

```python
def _finish(result):            # stamps, saves, copies to _state
    ...
```

After:

```python
def _publish(result: dict[str, JsonValue]) -> None:
    """Copy the operator-visible fields into the in-memory status, under the lock.

    Called on every check outcome, including failures that are deliberately not cached.
    Only ``str``/``bool``/``None`` fields move, so a loose payload can never smuggle a
    container into ``_state``.
    """

def _finish(result: dict[str, JsonValue], *, persist: bool = True) -> dict[str, JsonValue]:
    """Stamp, optionally persist, publish, and return a check result.

    ``persist=False`` is the failure path: the result is visible to the API immediately but
    never becomes a cache entry, so the next non-forced check really goes to the network.
    """
```

`_state` stays the single source `GET /api/updates` reads (`status()`), and
`update_state.json` becomes a **success-only** cache. `_set_status` keeps its current job
(install lifecycle states: `installing`, `installed`, `failed`, `blocked`) and is untouched.

### 3.2 Cache read

New helper used only by `check_for_update`:

```python
def _cached_check() -> dict[str, JsonValue] | None:
    """A fresh cached *successful* check, or None.

    A ``failed`` row written by an older version is ignored rather than migrated: the file
    is presentation state, and ignoring it is enough to stop the replay.
    """
```

`_load_cache()` and `_fresh()` keep their signatures and stay testable; the filtering
(`status == "failed"` → miss) lives in the new helper so the meaning is in one place.

### 3.3 Failure wording

```python
def _reason(error: BaseException) -> str:
    """One operator-readable line for a failure; the raw text is kept separately.

    Unwraps ``urllib.error.URLError`` to its ``reason`` and maps the three cases that
    actually happen — certificate verification, timeout, name resolution — to a sentence.
    Anything else falls back to ``str(error)`` so no information is lost.
    """

def _failed(reason: str, detail: str | None = None) -> dict[str, JsonValue]:
    """Build the failed-check payload; ``error`` is the sentence, ``detail`` the raw cause."""
```

`_failed` also carries `latest`/`download_url`/`sha256` as `None` so a failure never
renders a stale release tag next to the error.

`check_for_update` becomes:

```python
except urllib.error.HTTPError as e:
    if e.code == 404: ...up-to-date, cached...
    result = _failed(f"GitHub returned HTTP {e.code}", str(e))
    _finish(result, persist=False)
except (OSError, ValueError) as e:
    result = _failed(_reason(e), str(e))
    _finish(result, persist=False)
```

`apply_pending`'s catch-all uses `_reason(exc)` for `error` and keeps
`f"{type(exc).__name__}: {exc}"` in `detail`, so a download-time TLS failure reads the
same as a check-time one.

Threading: all of this runs on the caller's thread (FastAPI threadpool for the route,
`sf-auto-update` for the loop). `_state` access remains behind `_state_lock`; no new lock.

## 4. Frontend

`frontend/src/components/UpdateCard.tsx` gains two props:

```ts
interface Props {
  ...existing...
  checking: boolean
  onCheck: () => void
}
```

In the `failed` branch only, it renders the existing message plus:

```tsx
<Button appearance="bordered" onClick={onCheck} disabled={checking}>
  {checking ? 'Checking…' : 'Check again'}
</Button>
```

`frontend/src/queries.ts` gains:

```ts
export function useCheckUpdate(): ReturnType<typeof useMutation<UpdateStatus>>
```

— `api.checkUpdate()` (already present, previously unused), patching the `['updates']`
query cache with the response, exactly like `useInstallUpdate`.

`HomePage.tsx` passes `onCheck={() => check.mutate()}` and `checking={check.isPending}`);
`busy` (the job queue) deliberately does **not** disable a check.

No `types.ts` regeneration: `UpdateStatusView` and its payload are unchanged.

## 5. Collaborators and boundaries

| Caller | Calls | Effect |
|---|---|---|
| `POST /api/updates/checks` | `check_for_update(force=True)` | network; failure published, not cached |
| `GET /api/updates` | `status()` | reads `_state` only; never network |
| `AdminService._auto_update_loop` | `install_update(auto=True)` → `check_for_update(force=False)` | real retry every 10 min once failures stop being cached |
| `UpdateCard` → `useCheckUpdate` | `POST /api/updates/checks` | operator recovery without waiting for the loop |

## 6. What does not change

- TLS verification stays mandatory; no unverified context, no new dependency.
- Install guards, digest/version verification, `os.execv` restart, auto-loop cadence,
  attempted-version short-circuit, and the 6 h TTL for successful checks.
- The six-field `UpdateStatusView` payload and the generated TypeScript types.
