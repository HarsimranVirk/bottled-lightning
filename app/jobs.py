"""Job runner: executes extraction jobs on worker threads."""
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import config, store
from .browser import SalesforceSession, SessionExpired
from .extractors import extract_list_view

MAX_PLAYWRIGHT_WORKERS = 1  # serial: one browser at a time is plenty for POC

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
        with SalesforceSession(headless=True) as session:  # context manager below
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
    except SessionExpired:
        store.finish_job(job_id, "failed",
                         "session expired — run a manual login and retry")
    except Exception as e:
        store.finish_job(job_id, "failed", f"{type(e).__name__}: {e}")
        traceback.print_exc()
