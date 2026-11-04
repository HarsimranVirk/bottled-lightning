"""Response and request DTOs for the HTTP surface.

Wire format is camelCase (see ``docs/api-deviations.md``); Python stays snake_case via
the alias generator. These are the only models that cross the API boundary — domain
entities never leak into JSON.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, RootModel
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base DTO: camelCase on the wire, snake_case in Python."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WorkflowFieldView(ApiModel):
    key: str
    label: str
    value_type: str
    required: bool
    targets: list[str]


class WorkflowView(ApiModel):
    name: str
    route: str
    label: str
    list_url: str
    ref_kinds: list[str]
    fields: list[WorkflowFieldView]
    terminal_labels: dict[str, str]


class FieldView(ApiModel):
    extracted: str | None = None
    last_synced: str | None = None
    proposed: str | None = None
    applied: str | None = None
    status: str


class PageRefView(ApiModel):
    kind: str
    name: str
    url: str


class EditView(ApiModel):
    field: str
    old_value: str | None = None
    new_value: str | None = None
    at: datetime


class JobView(ApiModel):
    id: int
    workflow: str
    item: str
    kind: str
    status: str
    phase: str | None = None
    attempts: int
    lease_owner: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class ItemRowView(ApiModel):
    key: str
    status: str
    present: bool
    epoch: int
    record_url: str | None = None
    approved_at: str | None = None
    reason: str | None = None
    fields: dict[str, FieldView]
    active_job: JobView | None = None


class ItemDetailView(ItemRowView):
    attributes: dict[str, str | None]
    refs: list[PageRefView]
    edits: list[EditView]


class ItemsPageView(ApiModel):
    workflow: str
    count: int
    total: int
    rows: list[ItemRowView]


class JobLogsView(ApiModel):
    job: JobView
    logs: list[str]


class SyncView(ApiModel):
    workflow: str
    captured_at: datetime | None = None
    header_total: int | None = None
    rows_read: int
    valid: bool
    warning: str | None = None
    added: int
    updated: int
    closed: int


class SessionEventView(ApiModel):
    event: str
    detail: str
    at: datetime


class SessionView(ApiModel):
    state: str
    paused: bool
    cookies: int | None = None
    saved_at: datetime | None = None
    last_event: SessionEventView | None = None


class QueueView(ApiModel):
    concurrency: int
    in_flight: int
    paused: bool
    counts: dict[str, int]


class FieldValuesBody(RootModel[dict[str, str | None]]):
    """Flat body for editable values: ``{"loan_amount": "14,50,000", "tenure": null}``."""

    root: dict[str, str | None]


class ConcurrencyIn(ApiModel):
    concurrency: int


class UpdateStatusView(ApiModel):
    """Update-check result (a typed projection of ``app.updater``'s payload)."""

    status: str
    update_available: bool = False
    detail: str | None = None
    error: str | None = None
    latest: str | None = None
    download_url: str | None = None
