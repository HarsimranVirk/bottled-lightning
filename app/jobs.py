"""Job runner: executes extraction jobs on worker threads."""
import time as _time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path as _Path
from queue import Empty, Queue
from threading import Lock
from threading import Thread as _Thread

from . import config, store
from .browser import SalesforceSession, SessionExpired
from .extractors import (
    collect_record_links,
    extract_list_view,
    scrape_record_detail,
)

MAX_PLAYWRIGHT_WORKERS = 1  # serial: one browser at a time for extraction jobs

_executor = ThreadPoolExecutor(max_workers=MAX_PLAYWRIGHT_WORKERS,
                               thread_name_prefix="sf-extract")


def run_job_async(view_id: int, job_id: int) -> None:
    _executor.submit(_run_job, view_id, job_id)


def _run_job(view_id: int, job_id: int) -> None:
    view = store.get_view(view_id)
    if not view:
        store.finish_job(job_id, "failed", "view deleted")
        return
    try:
        with SalesforceSession(headless=True) as session:
            if not session.ensure_logged_in():
                store.finish_job(job_id, "failed", "session expired — run a manual login")
                return
            numbers, total = extract_list_view(session, view["url"], view["pattern"])
            if not numbers:
                store.finish_job(job_id, "failed", "no rows matched pattern",
                                 header_total=total, extracted=0)
                return
            store.record_rows(view_id, job_id, sorted(numbers))
            detail = "ok"
            if total is not None and len(numbers) != total:
                detail = f"count mismatch: header={total}, extracted={len(numbers)}"
            store.finish_job(job_id, "success", detail,
                             header_total=total, extracted=len(numbers))
            pick_deviations(session, view)
    except SessionExpired:
        store.finish_job(job_id, "failed",
                         "session expired — run a manual login and retry")
    except Exception as e:
        store.finish_job(job_id, "failed", f"{type(e).__name__}: {e}")
        traceback.print_exc()


def _scrape_worker(worker_no: int, queue: "Queue", stats: dict, lock: Lock) -> None:
    """One browser per worker thread: the Playwright sync API cannot be shared
    across threads, so each owns a fresh instance + its own profile dir.
    Cookie injection happens in start() from the DB snapshot."""
    session = None
    try:
        session = SalesforceSession(
            headless=True,
            profile_dir=_Path(str(config.PROFILE_DIR) + f"_w{worker_no}"),
        ).__enter__()
        while True:
            try:
                value, href = queue.get_nowait()
            except Empty:
                break
            t1 = _time.time()
            try:
                det = scrape_record_detail(session, href)
            except Exception as e:  # noqa: BLE001 - one bad record must not kill the rest
                print(f"! {value}: {type(e).__name__}: {e}")
                with lock:
                    stats["failed"] = stats.get("failed", 0) + 1
                continue
            if not det:
                with lock:
                    stats["failed"] = stats.get("failed", 0) + 1
                continue
            for i_ref, ref in enumerate(det.pop("page_refs"), start=1):
                store.upsert_deviation_page_ref(value, i_ref, ref["name"],
                                                ref.get("kind", "record"),
                                                ref["url"])
            store.upsert_deviation_detail(value, **det)
            with lock:
                stats["picked"] = stats.get("picked", 0) + 1
                elapsed = _time.time() - t1
                stats["times"].append(elapsed)
                n = stats["picked"]
                print(f"* [{n}] {value} picked in {elapsed:.1f}s"
                      f" (avg {(_time.time() - stats['t0']) / n:.1f}s)")
    finally:
        if session is not None:
            session.close()


def pick_deviations(session, view) -> None:
    """Post-extraction sweep: map each deviation to its record page, then pick
    the 'Loan Deviation Description' in parallel with per-thread browsers.
    The list-view session stays untouched; workers use their own."""
    links = collect_record_links(session.page, view["pattern"],
                                 target=len(store.latest_values(view["id"])))
    print(f"* record links mapped: {len(links)}")
    queue: "Queue" = Queue()
    for item in sorted(links.items()):
        queue.put(item)
    stats = {"picked": 0, "failed": 0, "t0": _time.time(), "times": []}
    lock = Lock()
    n_workers = min(config.SCRAPE_WORKERS, max(1, len(links)))
    workers = [
        _Thread(target=_scrape_worker, args=(w, queue, stats, lock),
                name=f"sf-pick-{w}", daemon=True)
        for w in range(n_workers)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    total = _time.time() - stats["t0"]
    times = sorted(stats["times"])
    avg = sum(times) / len(times) if times else 0.0
    med = times[len(times) // 2] if times else 0.0
    print(f"* descriptions picked: {stats['picked']}/{len(links)}"
          f" failed={stats['failed']} in {total:.1f}s"
          f" (avg {avg:.1f}s, median {med:.1f}s per deviation,"
          f" {n_workers} workers)")
