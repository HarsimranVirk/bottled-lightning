"""REST endpoints."""

import contextlib
import threading
from typing import Literal, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.types import (
    DeviationRow,
    DeviationsResponse,
    HistoryResponse,
    HistoryRow,
    JobRecord,
    JsonValue,
    LatestRow,
    LoginState,
    PageRef,
    ResultsResponse,
    ResyncState,
    SessionEventInfo,
    SessionInfo,
    StartLoginResponse,
    ViewRecord,
)

from . import config, store, sync
from . import legacy_jobs as jobs

router = APIRouter(prefix="/api")

# --- login state ---
_login_lock = threading.Lock()
_login_state: dict[str, str] = {"status": "idle", "detail": ""}


def _set_login_state(status: str, detail: str = "") -> None:
    _login_state["status"] = status
    _login_state["detail"] = detail


class LoginIn(BaseModel):
    reset: bool = False


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=10)
    pattern: str = Field(default=r"Deviation-\d+-\d+", max_length=120)


class WorkersIn(BaseModel):
    count: int = Field(ge=1, le=32)


class DecisionIn(BaseModel):
    decision: Literal["accept", "reject", "pending"] = Field(pattern="^(accept|reject|pending)$")
    property_value: str | None = None
    loan_amount: str | None = None
    tenure: str | None = None
    emi: str | None = None


# --- views ---
@router.get("/views")
def list_views() -> list[dict[str, str | int | None]]:
    return store.list_views()


@router.get("/views/{view_id}/results")
def get_view_results(view_id: int) -> ResultsResponse:
    view = store.get_view(view_id)
    if not view:
        raise HTTPException(404, "view not found")
    view_dict = dict(view)
    name = str(view_dict.get("name", ""))
    rows = [LatestRow.model_validate(r) for r in store.latest_values(view_id)]
    return ResultsResponse(view=name, rows=rows)


@router.post("/views", status_code=201)
def create_view(body: ViewIn) -> dict[str, str | int | None]:
    if "lightning.force.com/lightning/o/" not in body.url:
        raise HTTPException(400, "URL must be a Lightning list view URL")
    return store.add_view(body.name, body.url, body.pattern)


@router.delete("/views/{view_id}")
def delete_view(view_id: int) -> dict[str, int]:
    if not store.delete_view(view_id):
        raise HTTPException(404, "view not found")
    return {"deleted": view_id}


@router.post("/views/{view_id}/jobs", status_code=202)
@router.post("/views/{view_id}/run", status_code=202)
@router.post("/views/{view_id}/runs", status_code=202)
def create_view_job(view_id: int) -> dict[str, int]:
    view = store.get_view(view_id)
    if not view:
        raise HTTPException(404, "view not found")
    job_id = jobs.start_extraction(view_id, sync.current_snapshot())
    if job_id is None:
        raise HTTPException(409, "extraction already running")
    return {"job_id": job_id, "view_id": view_id}


# --- jobs ---
@router.get("/jobs")
def list_jobs() -> list[dict[str, str | int | None]]:
    return store.list_jobs()


@router.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict[str, str | int | None]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.get("/jobs/{job_id}/logs")
def get_job_logs(job_id: int) -> dict[str, list[str]]:
    return {"logs": store.get_job_logs(job_id)}


# --- deviations (Z02) ---
@router.get("/deviations")
def list_deviations(decision: str | None = None) -> DeviationsResponse:
    view = sync.z02_view()
    _vid = view.get("id")
    vid = _vid if isinstance(_vid, int) else 0
    jobs_list = store.list_jobs()
    last_job = next((j for j in jobs_list if j.get("view_id") == vid), None)
    view_record = ViewRecord.model_validate(view)
    lc = view.get("latest_count")
    if isinstance(lc, int):
        view_record.latest_count = lc
    job_record = JobRecord.model_validate(last_job) if isinstance(last_job, dict) else None
    rows: list[DeviationRow] = []
    for r in store.latest_values(vid):
        det = store.get_deviation_details(str(r["value"]))
        refs = store.get_deviation_page_refs(str(r["value"]))
        page_refs = [PageRef.model_validate(ref) for ref in refs if isinstance(ref, dict)]
        row = DeviationRow(
            value=str(r.get("value", "")),
            first_seen=str(r.get("first_seen", "")),
            last_seen=str(r.get("last_seen", "")),
            approval_date=str(r.get("approval_date"))
            if r.get("approval_date") is not None
            else None,
            description=det.get("description") if det else None,
            decision=(det.get("decision") if det else None) or "pending",
            record_url=det.get("record_url") if det else None,
            page_refs=page_refs,
            opportunity_url=next(
                (str(ref["url"]) for ref in refs if ref["kind"] == "opportunity"), None
            ),
            cl_contract_url=next(
                (str(ref["url"]) for ref in refs if ref["kind"] == "cl_contract"), None
            ),
            collateral_url=next(
                (str(ref["url"]) for ref in refs if ref["kind"] == "collateral"), None
            ),
            lms2_collateral_url=next(
                (str(ref["url"]) for ref in refs if ref["kind"] == "lms2_collateral"), None
            ),
            lms2_cl_contract_url=next(
                (str(ref["url"]) for ref in refs if ref["kind"] == "lms2_cl_contract"), None
            ),
            property_value=det.get("property_value") if det else None,
            loan_amount=det.get("loan_amount") if det else None,
            tenure=det.get("tenure") if det else None,
            emi=det.get("emi") if det else None,
            requested_roi=det.get("requested_roi") if det else None,
            ideal_roi=det.get("ideal_roi") if det else None,
            updated_roi=det.get("updated_roi") if det else None,
            requested_variance=det.get("requested_variance") if det else None,
        )
        if decision is not None and row.decision != decision:
            continue
        rows.append(row)
    return DeviationsResponse(
        view=view_record, job=job_record, count=view_record.latest_count, rows=rows
    )


@router.get("/deviations/history")
def list_deviation_history(
    value: str | None = None,
    record_id: str | None = None,
    description: str | None = None,
    property_value: str | None = None,
    loan_amount: str | None = None,
    tenure: str | None = None,
    emi: str | None = None,
    requested_roi: str | None = None,
    ideal_roi: str | None = None,
    updated_roi: str | None = None,
    requested_variance: str | None = None,
    opportunity_url: str | None = None,
    cl_contract_url: str | None = None,
    collateral_url: str | None = None,
    lms2_collateral_url: str | None = None,
    lms2_cl_contract_url: str | None = None,
    sf_approval_date: str | None = None,
    decided_at: str | None = None,
    decided_from: str | None = None,
    decided_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> HistoryResponse:
    filters: dict[str, str] = {}
    for k, v in {
        "value": value,
        "record_id": record_id,
        "description": description,
        "property_value": property_value,
        "loan_amount": loan_amount,
        "tenure": tenure,
        "emi": emi,
        "requested_roi": requested_roi,
        "ideal_roi": ideal_roi,
        "updated_roi": updated_roi,
        "requested_variance": requested_variance,
        "opportunity_url": opportunity_url,
        "cl_contract_url": cl_contract_url,
        "collateral_url": collateral_url,
        "lms2_collateral_url": lms2_collateral_url,
        "lms2_cl_contract_url": lms2_cl_contract_url,
        "sf_approval_date": sf_approval_date,
        "decided_at": decided_at,
    }.items():
        if v is not None and v != "":
            filters[k] = v
    if decided_from:
        filters["decided_from"] = decided_from
    if decided_to:
        filters["decided_to"] = decided_to
    rows, total = store.list_deviation_history(filters, limit=limit, offset=offset)
    return HistoryResponse(
        rows=[HistoryRow.model_validate(r) for r in rows],
        total=total,
    )


@router.patch("/deviations/{value}")
def update_deviation(value: str, body: DecisionIn) -> dict[str, JsonValue]:
    if body.decision == "accept":
        store.upsert_deviation_detail(
            value,
            property_value=body.property_value,
            loan_amount=body.loan_amount,
            tenure=body.tenure,
            emi=body.emi,
        )
    store.set_deviation_decision(value, body.decision)
    if body.decision == "accept":
        store.archive_accepted_deviation(value)
        store.delete_deviation_active(value)
    det = store.get_deviation_details(value)
    if det is not None:
        return cast(dict[str, JsonValue], det)  # det values are str | None, a subset of JsonValue
    return {"value": value, "decision": body.decision}


@router.post("/deviations/jobs", status_code=202)
@router.post("/deviations/run", status_code=202)
@router.post("/deviations/runs", status_code=202)
def create_deviation_job(refresh: bool = False) -> dict[str, int]:
    vid = sync.z02_view_id()
    if not vid:
        raise HTTPException(500, "deviations view is not available")
    job_id = jobs.start_extraction(vid, sync.current_snapshot(), force=refresh)
    if job_id is None:
        raise HTTPException(409, "extraction already running")
    return {"job_id": job_id, "view_id": vid}


# --- workers ---
@router.get("/workers")
def get_workers() -> dict[str, int]:
    return {"scrape_workers": config.SCRAPE_WORKERS}


@router.patch("/workers")
def update_workers(body: WorkersIn) -> dict[str, int]:
    return {"scrape_workers": config.set_scrape_workers(body.count)}


# --- sessions ---
@router.get("/sessions")
def session_status() -> SessionInfo:
    from datetime import datetime

    snap = store.get_auth_snapshot()
    legacy_exists = config.AUTH_FILE.exists()
    auth_exists = snap is not None or legacy_exists
    snapshot_store: str | None = None
    if snap is not None:
        snapshot_store = "sqlite"
    elif legacy_exists:
        snapshot_store = "legacy-file"

    snapshot_created_at: str | None = None
    snapshot_org: str | None = None
    snapshot_cookie_count: int | None = None
    snapshot_age_seconds: int | None = None
    if snap is not None:
        snapshot_created_at = (
            str(snap.get("created_at")) if snap.get("created_at") is not None else None
        )
        snapshot_org = str(snap.get("org")) if snap.get("org") is not None else None
        cc = snap.get("cookie_count")
        snapshot_cookie_count = int(cc) if isinstance(cc, int) else None
        if snapshot_created_at:
            try:
                created = datetime.fromisoformat(snapshot_created_at)
                snapshot_age_seconds = int((datetime.now(created.tzinfo) - created).total_seconds())
            except ValueError:
                snapshot_age_seconds = None

    login_state = dict(_login_state)
    status_val = str(login_state.get("status", "idle"))
    login_payload = LoginState(
        status=status_val,
        detail=str(login_state.get("detail", "")),
        in_progress=status_val == "running",
    )

    recent_events_raw = store.list_session_events(limit=10)
    recent_events: list[SessionEventInfo] = []
    for ev in recent_events_raw:
        eid = ev.get("id")
        recent_events.append(
            SessionEventInfo(
                id=int(eid) if isinstance(eid, int) else None,
                event=str(ev.get("event")) if ev.get("event") is not None else None,
                detail=str(ev.get("detail")) if ev.get("detail") is not None else None,
                created_at=str(ev.get("created_at")) if ev.get("created_at") is not None else None,
            )
        )

    last_login: str | None = snapshot_created_at

    return SessionInfo(
        org=config.ORG_BASE,
        auth_snapshot_exists=auth_exists,
        login=login_payload,
        recent_events=recent_events,
        last_login=last_login,
        snapshot_created_at=snapshot_created_at,
        snapshot_org=snapshot_org,
        snapshot_cookie_count=snapshot_cookie_count,
        snapshot_age_seconds=snapshot_age_seconds,
        snapshot_store=snapshot_store,
    )


@router.post("/sessions", status_code=202)
def create_session(body: LoginIn | None = None) -> StartLoginResponse:
    reset = bool(body.reset) if body is not None else False
    with _login_lock:
        if _login_state.get("status") == "running":
            return StartLoginResponse(status="running")
        _set_login_state("running", "login in progress — complete it in the browser window")

    def _run() -> None:
        try:
            from . import browser
            from . import legacy_jobs as jobs

            ok = browser.do_manual_login(reset=reset)
            if ok:
                _set_login_state("success", "session snapshot saved")
                with contextlib.suppress(Exception):
                    store.record_session_event("login", "manual login succeeded")
                with contextlib.suppress(Exception):
                    jobs.restart_pool()
            else:
                _set_login_state("failed", "manual login timed out")
                with contextlib.suppress(Exception):
                    store.record_session_event("login", "manual login timed out")
        except Exception as e:  # noqa: BLE001
            _set_login_state("failed", f"{type(e).__name__}: {e}")
            with contextlib.suppress(Exception):
                store.record_session_event("login", f"failed: {type(e).__name__}: {e}")

    threading.Thread(target=_run, name="manual-login", daemon=True).start()
    return StartLoginResponse(status="started", login_wait_seconds=config.LOGIN_WAIT_SECONDS)


@router.delete("/sessions")
def delete_session() -> dict[str, str]:
    store.clear_auth_snapshot()
    return {"status": "cleared"}


# --- sync / resync queue ---
@router.post("/syncs", status_code=202)
@router.post("/deviations/syncs", status_code=202)
@router.post("/deviations/sync", status_code=202)
def create_sync() -> dict[str, str]:
    if not sync.trigger():
        raise HTTPException(409, "resync already running")
    return {"status": "started"}


@router.get("/syncs")
@router.get("/deviations/syncs")
def get_sync() -> ResyncState:
    return sync.state()


# --- updates (stub) ---
@router.get("/updates")
def update_status() -> dict[str, str]:
    from . import __version__

    return {"status": "ok", "app_version": __version__}


@router.get("/updates/checks")
@router.post("/updates/checks", status_code=200)
def update_checks() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/updates/installations", status_code=202)
def update_installations() -> dict[str, str]:
    return {"status": "started"}
