"""Shared types: pydantic models for complex state."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScrapedDetail(BaseModel):
    record_id: str | None = None
    record_url: str | None = None
    description: str | None = None
    property_value: str | None = None
    loan_amount: str | None = None
    tenure: str | None = None
    emi: str | None = None
    requested_roi: str | None = None
    ideal_roi: str | None = None
    updated_roi: str | None = None
    requested_variance: str | None = None
    page_refs: list[dict[str, str]] = Field(default_factory=list)
    opportunity_url: str | None = None
    cl_contract_url: str | None = None
    collateral_url: str | None = None
    lms2_collateral_url: str | None = None
    lms2_cl_contract_url: str | None = None
    skip: bool = False
    skip_reason: str | None = None


class DetailEntry(BaseModel):
    value: str = ""
    det: ScrapedDetail = Field(default_factory=ScrapedDetail)
    refs: list[dict[str, str]] = Field(default_factory=list)
    skip: bool = False
    skip_reason: str | None = None
    opportunity_url: str | None = None
    cl_contract_url: str | None = None
    collateral_url: str | None = None
    lms2_collateral_url: str | None = None
    lms2_cl_contract_url: str | None = None
    opportunity_product_type: str | None = None


class LoginState(BaseModel):
    status: str = "idle"
    detail: str = ""
    in_progress: bool = False


class SessionEventInfo(BaseModel):
    id: int | None = None
    event: str | None = None
    detail: str | None = None
    created_at: str | None = None


class StartLoginResponse(BaseModel):
    status: str = "started"
    login_wait_seconds: int = 0


class SessionInfo(BaseModel):
    org: str
    auth_snapshot_exists: bool = False
    login: LoginState = Field(default_factory=LoginState)
    recent_events: list[SessionEventInfo] = Field(default_factory=list)
    last_login: str | None = None
    checked_at: str | None = None
    snapshot_created_at: str | None = None
    snapshot_org: str | None = None
    snapshot_cookie_count: int | None = None
    snapshot_age_seconds: int | None = None
    snapshot_store: str | None = None


class PageRef(BaseModel):
    seq: int = 0
    name: str = ""
    kind: str = ""
    url: str = ""


class ViewRecord(BaseModel):
    id: int = 0
    name: str = ""
    url: str = ""
    pattern: str = ""
    created_at: str = ""
    latest_count: int = 0
    last_success: str | None = None

    model_config = {"extra": "allow"}


class JobRecord(BaseModel):
    id: int = 0
    view_id: int = 0
    status: str = ""
    detail: str | None = None
    header_total: int | None = None
    extracted: int | None = None
    started_at: str = ""
    finished_at: str | None = None

    model_config = {"extra": "allow"}


class DeviationRow(BaseModel):
    value: str = ""
    first_seen: str = ""
    last_seen: str = ""
    approval_date: str | None = None
    description: str | None = None
    decision: str | None = None
    record_url: str | None = None
    page_refs: list[PageRef] = Field(default_factory=list)
    opportunity_url: str | None = None
    cl_contract_url: str | None = None
    collateral_url: str | None = None
    lms2_collateral_url: str | None = None
    lms2_cl_contract_url: str | None = None
    property_value: str | None = None
    loan_amount: str | None = None
    tenure: str | None = None
    emi: str | None = None
    requested_roi: str | None = None
    ideal_roi: str | None = None
    updated_roi: str | None = None
    requested_variance: str | None = None


class DeviationsResponse(BaseModel):
    view: ViewRecord
    job: JobRecord | None = None
    count: int = 0
    rows: list[DeviationRow] = Field(default_factory=list)


class ResyncQueue(BaseModel):
    pending: int = 0
    accept: int = 0
    reject: int = 0


class ResyncResult(BaseModel):
    sf_count: int = 0
    header_total: int | None = None
    count_mismatch: bool = False
    db_count: int = 0
    new_in_sf: list[str] = Field(default_factory=list)
    missing_in_sf: list[str] = Field(default_factory=list)
    added: list[str] | None = None
    removed: list[str] | None = None
    queue: ResyncQueue = Field(default_factory=ResyncQueue)


class ResyncState(BaseModel):
    status: str = "idle"
    detail: str = ""
    result: ResyncResult | None = None
    busy: bool = False
    cycle: int = 0
    interval_seconds: int = 0
    last_run_at: str | None = None
    job_running: bool = False


class ListSnapshot(BaseModel):
    """One list-view visit, reused by extraction jobs instead of a second visit."""

    numbers: set[str] = Field(default_factory=set)
    total: int | None = None
    links: dict[str, str] = Field(default_factory=dict)
    approval_dates: dict[str, str] = Field(default_factory=dict)
    captured_at: str = ""


class LatestRow(BaseModel):
    value: str = ""
    first_seen: str = ""
    last_seen: str = ""


class ResultsResponse(BaseModel):
    view: str = ""
    rows: list[LatestRow] = Field(default_factory=list)


class HistoryRow(BaseModel):
    id: int = 0
    value: str = ""
    sf_approval_date: str | None = None
    decided_at: str | None = None
    archived_at: str = ""
    record_id: str | None = None
    record_url: str | None = None
    description: str | None = None
    property_value: str | None = None
    loan_amount: str | None = None
    tenure: str | None = None
    emi: str | None = None
    requested_roi: str | None = None
    ideal_roi: str | None = None
    updated_roi: str | None = None
    requested_variance: str | None = None
    opportunity_url: str | None = None
    cl_contract_url: str | None = None
    collateral_url: str | None = None
    lms2_collateral_url: str | None = None
    lms2_cl_contract_url: str | None = None
    page_refs_json: str | None = None


class HistoryResponse(BaseModel):
    rows: list[HistoryRow] = Field(default_factory=list)
    total: int = 0


class State(BaseModel):
    numbers: set[str] = Field(default_factory=set)
    total: int | None = None
    links: dict[str, str] = Field(default_factory=dict)
    details: list[DetailEntry] = Field(default_factory=list)
    refs: list[dict[str, str]] = Field(default_factory=list)
    skip_reason: str | None = None
    skipped: int = 0
    failed: int = 0
    product_cache: dict[str, str | None] = Field(default_factory=dict, alias="_product_cache")

    model_config = {"populate_by_name": True}


JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
