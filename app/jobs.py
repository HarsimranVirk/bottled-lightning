"""Job runner: persistent worker pool with always-alive browser sessions."""

import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Thread
from typing import cast

from app.deviations.types import ScrapedDetail

from . import config, store
from .browser import SalesforceSession, SessionExpired
from .deviations_z02 import PROFILE
from .deviations_z02.pipeline import extract_list_and_links, extract_one_deviation

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
def run_job_async(view_id: int, job_id: int) -> None:
    _executor.submit(_run_job, view_id, job_id)


def _log(job_id: int, message: str) -> None:
    print(message, flush=True)
    try:
        store.append_job_log(job_id, message)
    except Exception as e:  # noqa: BLE001
        print(f"! log failed: {e}", file=__import__("sys").stderr)


MAX_PLAYWRIGHT_WORKERS = 1
_executor = ThreadPoolExecutor(max_workers=MAX_PLAYWRIGHT_WORKERS, thread_name_prefix="sf-extract")


def _run_job(view_id: int, job_id: int) -> None:
    try:
        _log(job_id, f"starting extraction for view {view_id}")
        session = SalesforceSession(headless=True)
        session.__enter__()
        try:
            if not session.ensure_logged_in():
                store.finish_job(job_id, "failed", "session expired — run a manual login")
                _log(job_id, "session expired — run a manual login")
                return
            numbers, total, links, approval_dates = extract_list_and_links(
                PROFILE, session, lambda m: _log(job_id, m)
            )
            _log(job_id, f"extracted {len(numbers)} (header total {total})")
            if not numbers:
                store.finish_job(
                    job_id, "failed", "no rows matched pattern", header_total=total, extracted=0
                )
                _log(job_id, "no rows matched pattern")
                return
            store.record_rows(view_id, job_id, sorted(numbers), approval_dates=approval_dates)
            refresh = store.resync_queue(view_id, numbers)
            _added = refresh.get("added") if isinstance(refresh, dict) else None
            _removed = refresh.get("removed") if isinstance(refresh, dict) else None
            _added = _added if isinstance(_added, list) else []
            _removed = _removed if isinstance(_removed, list) else []
            _log(job_id, (f"queue resynced: {len(_added)} added, {len(_removed)} removed"))
            detail = "ok"
            if total is not None and len(numbers) != total:
                detail = f"count mismatch: header={total}, extracted={len(numbers)}"

            try:
                session.close()
            except Exception as e:  # noqa: BLE001
                print(f"! close failed: {e}", file=__import__("sys").stderr)

            results: list[dict[str, str | int | None]] = []
            rlock = __import__("threading").Lock()

            def make_task(value: str, href: str) -> Callable[[SalesforceSession], None]:
                def task(sess: SalesforceSession) -> None:
                    try:
                        entry = extract_one_deviation(
                            PROFILE, sess, value, href, lambda m: _log(job_id, f"[worker] {m}")
                        )
                    except Exception as e:  # noqa: BLE001
                        _log(job_id, f"FAILED {value}: {type(e).__name__}: {e}")
                        traceback.print_exc()
                        return
                    with rlock:
                        results.append(cast(dict[str, str | int | None], entry.model_dump()))
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

                return task

            for item in sorted(links.items()):
                submit_task(make_task(item[0], item[1]))

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
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception as e:  # noqa: BLE001
                    print(f"! close failed: {e}", file=__import__("sys").stderr)
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
