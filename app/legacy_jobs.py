"""Job runner: persistent worker pool with always-alive browser sessions."""

import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Thread

from app.deviations.types import ScrapedDetail

from . import config, store
from .browser import SalesforceSession, SessionExpired
from .deviations_z02 import PROFILE
from .deviations_z02.pipeline import extract_one_deviation
from .types import JsonValue, ListSnapshot

# ---------------------------------------------------------------------------
# Persistent worker pool
# ---------------------------------------------------------------------------
_task_queue: Queue[Callable[[SalesforceSession], None] | None] = Queue()
_workers: list[Thread] = []
_pool_started: bool = False
_pool_size: int = 0


def _worker_loop(worker_no: int) -> None:
    """One always-alive worker: owns a single browser session."""
    session = SalesforceSession(
        headless=True,
        profile_dir=__import__("pathlib").Path(str(config.PROFILE_DIR) + f"_w{worker_no}"),
    )
    session.__enter__()
    try:
        if not session.ensure_logged_in():
            print(f"[w{worker_no}] session expired at startup", flush=True)
        while True:
            task = _task_queue.get()
            if task is None:  # sentinel -> stop
                _task_queue.task_done()
                break
            try:
                task(session)
            except Exception as e:  # noqa: BLE001
                print(f"[w{worker_no}] task failed: {type(e).__name__}: {e}", flush=True)
                traceback.print_exc()
            finally:
                _task_queue.task_done()
    finally:
        try:
            session.close()
        except Exception as e:  # noqa: BLE001
            print(f"[w{worker_no}] close failed: {e}", flush=True)


def _start_pool(n: int) -> None:
    global _pool_started, _pool_size
    if _pool_started:
        return
    _pool_size = max(1, n)
    for w in range(_pool_size):
        t = Thread(target=_worker_loop, args=(w,), name=f"sf-worker-{w}", daemon=True)
        t.start()
        _workers.append(t)
    _pool_started = True


def _stop_pool() -> None:
    global _pool_started
    if not _pool_started:
        return
    for _ in _workers:
        _task_queue.put(None)
    for t in _workers:
        t.join(timeout=30)
    _workers.clear()
    _pool_started = False


def submit_task(task: Callable[[SalesforceSession], None]) -> None:
    """Enqueue a task (callable receiving a session) for the worker pool."""
    if not _pool_started:
        _start_pool(config.SCRAPE_WORKERS)
    _task_queue.put(task)


def pool_size() -> int:
    if not _pool_started:
        _start_pool(config.SCRAPE_WORKERS)
    return _pool_size


def restart_pool() -> None:
    _stop_pool()
    _start_pool(config.SCRAPE_WORKERS)


def shutdown_pool() -> None:
    _stop_pool()


# ---------------------------------------------------------------------------
# Job runner
# ---------------------------------------------------------------------------
def run_job_async(
    view_id: int,
    job_id: int,
    snapshot: ListSnapshot | None = None,
    values: set[str] | None = None,
    force: bool = False,
) -> None:
    _executor.submit(_run_job, view_id, job_id, snapshot, values, force)


_trigger_lock = threading.Lock()


def start_extraction(
    view_id: int,
    snapshot: ListSnapshot | None = None,
    values: set[str] | None = None,
    *,
    only_if_idle: bool = False,
    force: bool = False,
) -> int | None:
    """Create a job row and queue it. Returns None if ``only_if_idle`` blocked it."""
    with _trigger_lock:
        if only_if_idle and store.running_jobs() > 0:
            return None
        job_id = store.create_job(view_id)
        run_job_async(view_id, job_id, snapshot, values, force)
        return job_id


def _log(job_id: int, message: str) -> None:
    print(message, flush=True)
    try:
        store.append_job_log(job_id, message)
    except Exception as e:  # noqa: BLE001
        print(f"! log failed: {e}", file=__import__("sys").stderr)


MAX_PLAYWRIGHT_WORKERS = 1
_executor = ThreadPoolExecutor(max_workers=MAX_PLAYWRIGHT_WORKERS, thread_name_prefix="sf-extract")


def _run_job(
    view_id: int,
    job_id: int,
    snapshot: ListSnapshot | None = None,
    values: set[str] | None = None,
    force: bool = False,
) -> None:
    try:
        _log(job_id, f"starting extraction for view {view_id}")
        snap = snapshot
        if snap is None:
            # never visit the list view here: the resync loop owns that visit
            from . import sync

            _log(job_id, "waiting for the background resync to visit the list view")
            snap = sync.wait_for_snapshot()
        if snap is None:
            store.finish_job(
                job_id, "failed", "no Salesforce list snapshot — resync loop unavailable"
            )
            _log(job_id, "no Salesforce list snapshot — resync loop unavailable")
            return
        numbers = snap.numbers
        total = snap.total
        links = snap.links
        _log(
            job_id,
            f"reusing list snapshot from {snap.captured_at}: "
            f"{len(numbers)} deviations (header total {total})",
        )
        if not numbers:
            store.finish_job(
                job_id, "failed", "no rows matched pattern", header_total=total, extracted=0
            )
            _log(job_id, "no rows matched pattern")
            return
        store.record_rows(view_id, job_id, sorted(numbers), approval_dates=snap.approval_dates)
        refresh = store.resync_queue(view_id, numbers, approval_dates=snap.approval_dates)
        _added = refresh.get("added")
        _removed = refresh.get("removed")
        _added = _added if isinstance(_added, list) else []
        _removed = _removed if isinstance(_removed, list) else []
        _log(job_id, (f"queue resynced: {len(_added)} added, {len(_removed)} removed"))
        detail = "ok"
        if total is not None and len(numbers) != total:
            detail = f"count mismatch: header={total}, extracted={len(numbers)}"

        results: list[dict[str, JsonValue]] = []
        rlock = threading.Lock()

        def make_task(value: str, href: str) -> Callable[[SalesforceSession], None]:
            def task(sess: SalesforceSession) -> None:
                try:
                    entry = extract_one_deviation(
                        PROFILE,
                        sess,
                        value,
                        href,
                        lambda m: _log(job_id, f"[worker] {m}"),
                        force=force,
                    )
                except Exception as e:  # noqa: BLE001
                    _log(job_id, f"FAILED {value}: {type(e).__name__}: {e}")
                    traceback.print_exc()
                    return
                with rlock:
                    snapshot: dict[str, JsonValue] = entry.model_dump()
                    results.append(snapshot)
                refs = entry.refs
                for i_ref, ref in enumerate(refs, start=1):
                    if not isinstance(ref, dict):
                        continue
                    store.upsert_deviation_page_ref(
                        value,
                        i_ref,
                        str(ref.get("name", "")),
                        str(ref.get("kind", "record")),
                        str(ref.get("url", "")),
                    )
                det = entry.det
                if det and (det.description is not None or det.record_url is not None):
                    store.upsert_deviation_detail(value, **_clean_det(det))
                skip = bool(entry.skip)
                reason = entry.skip_reason
                if skip:
                    store.set_deviation_decision(value, "reject")
                    _log(job_id, f"skipped {value}: {reason}")
                else:
                    _log(job_id, f"picked {value}")
                # one-shot: never revisit a record that has been visited
                store.mark_deviation_extracted(value)

            return task

        targets = sorted(
            (value, href) for value, href in links.items() if values is None or value in values
        )
        if not targets:
            _log(job_id, "nothing to extract — all details are already cached")
        for value, href in targets:
            submit_task(make_task(value, href))

        _task_queue.join()

        skipped = sum(1 for e in results if isinstance(e, dict) and e.get("skip"))
        if skipped:
            detail = f"{detail}; {skipped} skipped"
        skip_reasons = [
            str(e.get("skip_reason"))
            for e in results
            if isinstance(e, dict) and e.get("skip_reason")
        ]
        if skip_reasons:
            detail = f"{detail}; " + "; ".join(skip_reasons)
        store.finish_job(job_id, "success", detail, header_total=total, extracted=len(numbers))
        _log(job_id, f"job finished: {detail}")
    except SessionExpired:
        store.finish_job(job_id, "failed", "session expired — run a manual login and retry")
        _log(job_id, "session expired — run a manual login and retry")
    except Exception as e:  # noqa: BLE001
        store.finish_job(job_id, "failed", f"{type(e).__name__}: {e}")
        _log(job_id, f"FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()


def _clean_det(det: ScrapedDetail) -> dict[str, str | None]:
    allowed = {
        "record_id",
        "record_url",
        "description",
        "property_value",
        "loan_amount",
        "tenure",
        "emi",
        "requested_roi",
        "ideal_roi",
        "updated_roi",
        "requested_variance",
        "opportunity_url",
        "cl_contract_url",
        "collateral_url",
        "lms2_collateral_url",
        "lms2_cl_contract_url",
    }
    out: dict[str, str | None] = {}
    for k, v in det.model_dump().items():
        if k in allowed:
            out[k] = v if isinstance(v, str) or v is None else None
    return out
