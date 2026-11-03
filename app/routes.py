"""REST endpoints."""
import csv
import io
import shutil
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import browser, config, jobs, store
from .browser import SalesforceSession, SessionExpired
from .extractors import extract_list_view

router = APIRouter(prefix="/api")


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=10)
    pattern: str = Field(default=r"Deviation-\d+-\d+", max_length=120)


@router.get("/views")
def get_views():
    return store.list_views()


@router.post("/views", status_code=201)
def post_view(body: ViewIn):
    if "lightning.force.com/lightning/o/" not in body.url:
        raise HTTPException(400, "URL must be a Lightning list view URL")
    return store.add_view(body.name, body.url, body.pattern)


@router.delete("/views/{view_id}")
def del_view(view_id: int):
    if not store.delete_view(view_id):
        raise HTTPException(404, "view not found")
    return {"deleted": view_id}


@router.post("/views/{view_id}/run", status_code=202)
def run_view(view_id: int):
    view = store.get_view(view_id)
    if not view:
        raise HTTPException(404, "view not found")
    job_id = store.create_job(view_id)
    jobs.run_job_async(view_id, job_id)
    return {"job_id": job_id, "view_id": view_id}


@router.get("/jobs")
def get_jobs():
    return store.list_jobs()


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.get("/views/{view_id}/results")
def get_results(view_id: int):
    if not store.get_view(view_id):
        raise HTTPException(404, "view not found")
    return {"view": store.get_view(view_id)["name"], "rows": store.latest_values(view_id)}


@router.get("/views/{view_id}/results.csv")
def get_results_csv(view_id: int):
    if not store.get_view(view_id):
        raise HTTPException(404, "view not found")
    rows = store.latest_values(view_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["DeviationNo", "FirstSeen", "LastSeen"])
    for r in rows:
        w.writerow([r["value"], r["first_seen"], r["last_seen"]])
    buf.seek(0)
    filename = f"view{view_id}_deviations.csv"
    return StreamingResponse(buf, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


# --- login machinery ------------------------------------------------------------
class LoginIn(BaseModel):
    reset: bool = False


_login_lock = threading.Lock()
_login_state: Dict[str, str] = {"status": "idle", "detail": ""}


def _set_login_state(status: str, detail: str = "") -> None:
    _login_state["status"] = status
    _login_state["detail"] = detail


def _run_login(reset: bool) -> None:
    from . import config

    try:
        ok = browser.do_manual_login(reset=reset)
        if ok:
            _set_login_state("success", "session saved to data/auth.json")
            store.record_session_event("login_success", "snapshot saved")
        else:
            _set_login_state("failed", "timed out waiting for manual login")
            store.record_session_event("login_timed_out", "no login within window")
    except Exception as e:  # noqa: BLE001 - report any login crash to the UI
        _set_login_state("failed", f"{type(e).__name__}: {e}")
        traceback.print_exc()
        store.record_session_event("login_failed", f"{type(e).__name__}: {e}")
    finally:
        _login_lock.release()


def _clear_session_files() -> None:
    """Wipe session state: DB snapshot rows, legacy auth.json, browser profile."""
    from . import config

    store.clear_auth_snapshot()
    shutil.rmtree(config.PROFILE_DIR, ignore_errors=True)
    if config.AUTH_FILE.exists():
        config.AUTH_FILE.unlink()


# --- packaged Z02 deviations view ------------------------------------------
Z02_VIEW_NAME = "Loan Deviations Z2"
Z02_OBJECT_API = "Consumer_Loan_Deviation__c"
Z02_FILTER = "Z2_Loan_para_pricing1"
Z02_PATTERN = r"Deviation-\d+-\d+"  # middle segment is DDMMYYYY, see AGENTS.md #5


def _get_z02_view():
    """The Z2 view row, creating it on first use if the table is empty."""
    for v in store.list_views():
        if v["name"] == Z02_VIEW_NAME:
            return v
        if Z02_FILTER in v["url"]:
            return v
    url = config.LIST_URL_TEMPLATE.format(
        host=config.ORG_BASE, object_api=Z02_OBJECT_API, filter=Z02_FILTER)
    store.add_view(Z02_VIEW_NAME, url, Z02_PATTERN)
    return store.list_views()[0]


@router.get("/deviations")
def get_deviations():
    """All deviations from the Z2 list view (latest extraction + description
    picks from the record pages)."""
    view = _get_z02_view()
    jobs_list = store.list_jobs(limit=200)
    last_job = next((j for j in jobs_list if j["view_id"] == view["id"]), None)
    rows = []
    for r in store.latest_values(view["id"]):
        row = dict(r)
        det = store.get_deviation_details(r["value"])
        row["description"] = det.get("description") if det else None
        row["decision"] = (det.get("decision") if det else None) or "pending"
        row["record_url"] = det.get("record_url") if det else None
        refs = store.get_deviation_page_refs(r["value"])
        row["page_refs"] = refs
        row["opportunity_url"] = next(
            (ref["url"] for ref in refs if ref["kind"] == "opportunity"), None)
        for field in ("property_value", "loan_amount", "tenure", "emi"):
            row[field] = det.get(field) if det else None
        rows.append(row)
    return {
        "view": dict(view),
        "job": last_job,
        "count": view["latest_count"],
        "rows": rows,
    }


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(accept|reject|pending)$")
    property_value: Optional[str] = None
    loan_amount: Optional[str] = None
    tenure: Optional[str] = None
    emi: Optional[str] = None


@router.post("/deviations/{value}/decision")
def set_decision(value: str, body: DecisionIn):
    """Human-in-the-loop decision. On accept, the (possibly hand-corrected)
    new loan parameters cloned from the description are stored for the
    multi-page update workflow."""
    if body.decision == "accept":
        store.upsert_deviation_detail(
            value,
            property_value=body.property_value,
            loan_amount=body.loan_amount,
            tenure=body.tenure,
            emi=body.emi,
        )
    store.set_deviation_decision(value, body.decision)
    return store.get_deviation_details(value) or {"value": value,
                                                 "decision": body.decision}


@router.post("/deviations/run", status_code=202)
def run_deviations():
    view = _get_z02_view()
    job_id = store.create_job(view["id"])
    jobs.run_job_async(view["id"], job_id)
    return {"job_id": job_id, "view_id": view["id"]}


@router.post("/deviations/resync", status_code=202)
def start_resync():
    """Cross-check the queue against the live SF list view: opens the list
    (Printable View — no record pages), diffs numbers vs the DB."""
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "resync already in progress")
    _set_sync_state("running", "checking Salesforce list view…")
    threading.Thread(target=_run_resync, daemon=True).start()
    return {"status": "running"}


@router.get("/deviations/resync")
def resync_status():
    return _sync_state


# --- resync machinery -----------------------------------------------------------
_sync_lock = threading.Lock()
_sync_state: Dict[str, Any] = {"status": "idle", "detail": "", "result": None}


def _set_sync_state(status: str, detail: str = "", result: Optional[dict] = None) -> None:
    _sync_state["status"] = status
    _sync_state["detail"] = detail
    _sync_state["result"] = result


def _run_resync():
    from . import routes
    try:
        view = routes._get_z02_view()
        with SalesforceSession(headless=True) as session:
            if not session.ensure_logged_in():
                _set_sync_state("failed", "session expired — run a manual login")
                return
            numbers, total = extract_list_view(
                session, view["url"], view["pattern"])
        db_values = {r["value"] for r in store.latest_values(view["id"])}
        sf_values = set(numbers)
        decided = store.count_pending_details(pending_only=False)
        result = {
            "sf_count": len(sf_values),
            "header_total": total,
            "count_mismatch": total is not None and len(sf_values) != total,
            "db_count": len(db_values),
            "new_in_sf": sorted(sf_values - db_values),
            "missing_in_sf": sorted(db_values - sf_values),
            "queue": {
                "pending": sum(1 for d in decided if d["decision"] == "pending"),
                "accept": sum(1 for d in decided if d["decision"] == "accept"),
                "reject": sum(1 for d in decided if d["decision"] == "reject"),
            },
        }
        detail = "queue matches Salesforce" if (
            result["new_in_sf"] == [] and result["missing_in_sf"] == []
            and not result["count_mismatch"]) else (
            f"{len(result['new_in_sf'])} new in SF, "
            f"{len(result['missing_in_sf'])} missing, "
            f"count mismatch: {result['count_mismatch']}")
        _set_sync_state("done", detail, result)
    except SessionExpired:
        _set_sync_state("failed", "session expired — run a manual login")
    except Exception as e:  # noqa: BLE001
        _set_sync_state("failed", f"{type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        _sync_lock.release()


@router.get("/session")
def session_status():
    """Session snapshot info from the DB + login progress; the UI polls this
    while logging in."""
    from . import config

    state = dict(_login_state)
    with _login_lock:
        state["in_progress"] = _login_state["status"] == "running"

    snap = store.get_auth_snapshot()
    info: Dict[str, Any] = {
        "org": config.ORG_BASE,
        "auth_snapshot_exists": snap is not None,
        "login": state,
        "recent_events": store.list_session_events(limit=5),
    }
    auth_event = store.last_session_event("login_success")
    info["last_login"] = auth_event["created_at"] if auth_event else None

    if snap:
        info["snapshot_created_at"] = snap["created_at"]
        info["snapshot_org"] = snap["org"]
        info["snapshot_cookie_count"] = snap["cookie_count"]
        try:
            age = time.time() - datetime.fromisoformat(snap["created_at"]).timestamp()
            info["snapshot_age_seconds"] = round(age)
        except ValueError:
            pass
        info["snapshot_store"] = "sqlite"
    elif config.AUTH_FILE.exists():
        # legacy file-based snapshot (pre-DB) — still injectable
        info["auth_snapshot_exists"] = None
        info["snapshot_store"] = "legacy-file"
    return info


@router.post("/session/login", status_code=202)
def start_login(body: Optional[LoginIn] = None):
    """Open a headful browser, wait for manual login, snapshot the session
    to data/auth.json. Returns 202; poll GET /api/session for progress."""
    from . import config

    reset = bool(body.reset) if body else False
    if not _login_lock.acquire(blocking=False):
        raise HTTPException(409, "login already in progress")
    if reset:
        _clear_session_files()
    store.record_session_event("login_started", "reset" if reset else "manual")
    _set_login_state("running", "a browser window is open — log in there")
    threading.Thread(target=_run_login, args=(reset,), daemon=True).start()
    return {"status": "running", "detail": _login_state["detail"],
            "login_wait_seconds": config.LOGIN_WAIT_SECONDS}


@router.post("/session/reset", status_code=202)
def reset_session():
    """Delete the saved session snapshot + browser profile. A new login is
    required afterwards."""
    if _login_state["status"] == "running":
        raise HTTPException(409, "cannot reset while a login is in progress")
    _clear_session_files()
    store.record_session_event("session_reset", "requested from UI")
    return {"status": "reset"}



_login_lock = threading.Lock()
_login_state: Dict[str, str] = {"status": "idle", "detail": ""}


def _set_login_state(status: str, detail: str = "") -> None:
    _login_state["status"] = status
    _login_state["detail"] = detail


def _run_login(reset: bool) -> None:
    from . import config

    try:
        ok = browser.do_manual_login(reset=reset)
        if ok:
            _set_login_state("success", "session saved to data/auth.json")
            store.record_session_event("login_success", "snapshot saved")
        else:
            _set_login_state("failed", "timed out waiting for manual login")
            store.record_session_event("login_timed_out", "no login within window")
    except Exception as e:  # noqa: BLE001 - report any login crash to the UI
        _set_login_state("failed", f"{type(e).__name__}: {e}")
        traceback.print_exc()
        store.record_session_event("login_failed", f"{type(e).__name__}: {e}")
    finally:
        _login_lock.release()
