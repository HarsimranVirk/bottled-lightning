"""Continuous queue resync loop.

One cycle = visit the Salesforce list view once, reconcile ``latest_values``
against it, and keep the visit as a :class:`ListSnapshot`. Extraction jobs
consume that snapshot instead of visiting the list view a second time.

The loop runs in a daemon thread and re-runs every
``config.RESYNC_INTERVAL_SECONDS`` seconds (30 by default).
"""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass

from . import config, jobs, store
from .browser import SalesforceSession
from .deviations_z02 import PROFILE
from .deviations_z02.pipeline import extract_list_and_links
from .types import ListSnapshot, ResyncQueue, ResyncResult, ResyncState

Z02_VIEW_NAME = "Loan Deviations Z02"
Z02_OBJECT_API = "Consumer_Loan_Deviation__c"
Z02_FILTER = "Z2_Loan_para_pricing1"
Z02_PATTERN = r"Deviation-\d+-\d+"


# ---------------------------------------------------------------------------
# Z02 view resolution (shared with the REST layer)
# ---------------------------------------------------------------------------
def z02_view() -> dict[str, str | int | None]:
    for v in store.list_views():
        if v["name"] == Z02_VIEW_NAME:
            return v
        if Z02_FILTER in str(v.get("url", "")):
            return v
    url = config.LIST_URL_TEMPLATE.format(
        host=config.ORG_BASE, object_api=Z02_OBJECT_API, filter=Z02_FILTER
    )
    store.add_view(Z02_VIEW_NAME, url, Z02_PATTERN)
    views = store.list_views()
    if not views:
        raise RuntimeError("failed to create the deviations view")
    return views[0]


def z02_view_id() -> int:
    raw = z02_view().get("id")
    return raw if isinstance(raw, int) else 0


# ---------------------------------------------------------------------------
# Loop state
# ---------------------------------------------------------------------------
@dataclass
class _State:
    status: str = "idle"
    detail: str = ""
    result: ResyncResult | None = None
    busy: bool = False
    cycle: int = 0
    last_run_at: str | None = None


_state = _State()
_state_lock = threading.Lock()

_snapshot: ListSnapshot | None = None
_snapshot_monotonic: float = 0.0
_snapshot_lock = threading.Lock()

_session: SalesforceSession | None = None
_session_lock = threading.Lock()

# value -> monotonic timestamp of the last auto-triggered extraction attempt
_attempted: dict[str, float] = {}

_thread: threading.Thread | None = None
_stop = threading.Event()
_wake = threading.Event()


# ---------------------------------------------------------------------------
# Browser session (one long-lived context, not one launch per cycle)
# ---------------------------------------------------------------------------
def _current_session() -> SalesforceSession:
    global _session
    with _session_lock:
        if _session is None:
            session = SalesforceSession(headless=True, profile_dir=config.SYNC_PROFILE_DIR)
            session.__enter__()
            _session = session
        return _session


def _drop_session() -> None:
    global _session
    with _session_lock:
        session, _session = _session, None
    if session is not None:
        with contextlib.suppress(Exception):
            session.close()


def _ensure_session() -> SalesforceSession:
    session = _current_session()
    if session.ensure_logged_in():
        return session
    # stale cookies: rebuild from the saved snapshot once before giving up
    _drop_session()
    session = _current_session()
    if not session.ensure_logged_in():
        _drop_session()
        raise RuntimeError("session expired — run a manual login")
    return session


# ---------------------------------------------------------------------------
# Snapshot access (used by extraction jobs)
# ---------------------------------------------------------------------------
def latest_snapshot(max_age_seconds: float | None = None) -> ListSnapshot | None:
    with _snapshot_lock:
        snapshot = _snapshot
        captured = _snapshot_monotonic
    if snapshot is None:
        return None
    if max_age_seconds is not None and time.monotonic() - captured > max_age_seconds:
        return None
    return snapshot.model_copy(deep=True)


def current_snapshot() -> ListSnapshot | None:
    """Snapshot an extraction job may reuse right now (a few sync cycles old at most)."""
    return latest_snapshot(max_age_seconds=float(max(60, config.RESYNC_INTERVAL_SECONDS * 3)))


def wait_for_snapshot(timeout: float | None = None) -> ListSnapshot | None:
    """Block until a fresh snapshot exists (the sync loop owns the list visit)."""
    limit = config.RESYNC_SNAPSHOT_WAIT_SECONDS if timeout is None else timeout
    deadline = time.monotonic() + limit
    while True:
        snapshot = current_snapshot()
        if snapshot is not None:
            return snapshot
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def _store_snapshot(snapshot: ListSnapshot) -> None:
    global _snapshot, _snapshot_monotonic
    with _snapshot_lock:
        _snapshot = snapshot
        _snapshot_monotonic = time.monotonic()


# ---------------------------------------------------------------------------
# One cycle
# ---------------------------------------------------------------------------
def _queue_tally(view_id: int) -> ResyncQueue:
    pending = accept = reject = 0
    for row in store.latest_values(view_id):
        det = store.get_deviation_details(str(row.get("value")))
        decision = (det.get("decision") if det else None) or "pending"
        if decision == "accept":
            accept += 1
        elif decision == "reject":
            reject += 1
        else:
            pending += 1
    return ResyncQueue(pending=pending, accept=accept, reject=reject)


def _sync_once() -> tuple[ResyncResult, ListSnapshot]:
    view_id = z02_view_id()
    if not view_id:
        raise RuntimeError("deviations view is not available")

    db_values = {str(r.get("value")) for r in store.latest_values(view_id)}
    session = _ensure_session()
    numbers, total, links, approval_dates = extract_list_and_links(
        PROFILE, session, lambda m: print(f"[sync] {m}", flush=True)
    )
    sf_values = {v for v in numbers if v}

    snapshot = ListSnapshot(
        numbers=sf_values,
        total=total,
        links=links,
        approval_dates=approval_dates,
        captured_at=store.now_iso(),
    )
    _store_snapshot(snapshot)

    data = store.resync_queue(view_id, sf_values, approval_dates=approval_dates)
    added = data.get("added")
    removed = data.get("removed")
    result = ResyncResult(
        sf_count=len(sf_values),
        header_total=total,
        count_mismatch=total is not None and len(sf_values) != total,
        db_count=len(db_values),
        new_in_sf=sorted(sf_values - db_values),
        missing_in_sf=sorted(db_values - sf_values),
        added=[str(x) for x in added] if isinstance(added, list) else [],
        removed=[str(x) for x in removed] if isinstance(removed, list) else [],
        queue=_queue_tally(view_id),
    )
    return result, snapshot


def _maybe_start_extraction(snapshot: ListSnapshot) -> None:
    """Kick off detail extraction for pending deviations, reusing this snapshot."""
    view_id = z02_view_id()
    if not view_id:
        return
    now = time.monotonic()
    due: set[str] = set()
    for row in store.latest_values(view_id):
        value = str(row.get("value"))
        det = store.get_deviation_details(value)
        decision = (det.get("decision") if det else None) or "pending"
        if decision != "pending":
            continue
        # one-shot: a visited record is final, so only unvisited values are due
        if det is not None and det.get("extracted_at") is not None:
            continue
        href = snapshot.links.get(value)
        if href is None:
            continue
        if now - _attempted.get(value, 0.0) < config.RESYNC_RETRY_COOLDOWN_SECONDS:
            continue
        due.add(value)
    alive = set(snapshot.links)
    for value in [v for v in _attempted if v not in alive]:
        del _attempted[value]
    if not due:
        return
    job_id = jobs.start_extraction(view_id, snapshot, values=due, only_if_idle=True)
    if job_id is None:
        return  # an extraction is already running; next cycle picks up the rest
    for value in due:
        _attempted[value] = now
    print(f"[sync] extraction job {job_id} started for {len(due)} deviation(s)", flush=True)


def _run_cycle() -> ResyncResult | None:
    with _state_lock:
        if _state.busy:
            return None
        _state.busy = True
        _state.status = "running"
        _state.detail = "visiting the Salesforce list view"
    try:
        result, snapshot = _sync_once()
    except Exception as e:  # noqa: BLE001
        _drop_session()
        with _state_lock:
            _state.busy = False
            _state.status = "failed"
            _state.detail = f"{type(e).__name__}: {e}"
            _state.last_run_at = store.now_iso()
        print(f"! resync failed: {type(e).__name__}: {e}", flush=True)
        return None
    with _state_lock:
        _state.busy = False
        _state.status = "done"
        _state.detail = f"resynced: {result.sf_count} in SF"
        _state.result = result
        _state.cycle += 1
        _state.last_run_at = store.now_iso()
    with contextlib.suppress(Exception):
        _maybe_start_extraction(snapshot)
    return result


# ---------------------------------------------------------------------------
# Public control surface
# ---------------------------------------------------------------------------
def state() -> ResyncState:
    with _state_lock:
        return ResyncState(
            status=_state.status,
            detail=_state.detail,
            result=_state.result,
            busy=_state.busy,
            cycle=_state.cycle,
            interval_seconds=config.RESYNC_INTERVAL_SECONDS,
            last_run_at=_state.last_run_at,
            job_running=store.running_jobs() > 0,
        )


def trigger() -> bool:
    """Request an immediate cycle. False when one is already running."""
    with _state_lock:
        if _state.busy:
            return False
    start()
    _wake.set()
    return True


def _loop() -> None:
    while not _stop.is_set():
        _wake.clear()
        _run_cycle()
        if _stop.is_set():
            break
        _wake.wait(timeout=float(config.RESYNC_INTERVAL_SECONDS))


def start() -> None:
    global _thread
    with _state_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        thread = threading.Thread(target=_loop, name="resync-loop", daemon=True)
        _thread = thread
    thread.start()


def stop() -> None:
    _stop.set()
    _wake.set()
    with _state_lock:
        thread = _thread
    if thread is not None:
        thread.join(timeout=30)
    _drop_session()
