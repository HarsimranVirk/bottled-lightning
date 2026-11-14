"""Response and request DTOs for the HTTP surface.

Wire format is camelCase (see ``docs/api-deviations.md``); Python stays snake_case via
the alias generator. These are the only models that cross the API boundary — domain
entities never leak into JSON.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel
from pydantic.alias_generators import to_camel

from app.config import NetworkProfile


class ApiModel(BaseModel):
    """Base DTO: camelCase on the wire, snake_case in Python."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WorkflowFieldView(ApiModel):
    """One catalogue entry, as the deck renders it."""

    key: str
    """Catalogue key used in edit payloads, e.g. ``tenure``."""

    label: str
    """Heading shown to the operator, e.g. ``EMI & other fixed payments incl. HFFC Loan``."""

    value_type: str
    """How the text is parsed for validation: ``amount``, ``months``, ``number`` or
    ``text``."""

    required: bool
    """Whether the operator must supply a value before submitting."""

    targets: list[str]
    """Object kinds this value is written to, in write order, e.g.
    ``["opportunity", "cl_contract"]``."""


class WorkflowView(ApiModel):
    """One registered workflow, enough for the SPA to build its screens."""

    name: str
    """Registry/database scope, e.g. ``deviations_z02``; sent back as the ``workflow``
    query parameter."""

    route: str
    """REST noun the endpoints are mounted under, e.g. ``deviations``."""

    label: str
    """Human-readable workflow name for the UI."""

    list_url: str | None
    """Lightning list URL this workflow refreshes (``filterName`` + ``fcf``); ``None``
    for a list-less workflow whose items are supplied manually."""

    ref_kinds: list[str]
    """Object kinds whose links every item carries, in display order."""

    fields: list[WorkflowFieldView]
    """Editable-field catalogue in display order."""

    terminal_labels: dict[str, str]
    """Status value → operator label override, e.g. ``{"completed": "Implemented"}``."""


class LinkBatchBody(ApiModel):
    """One paste of manually supplied item links."""

    links: list[str]
    """Lines exactly as the operator pasted them; blank lines are ignored and each
    remaining line is parsed by the workflow's intake."""


class RejectedLinkView(ApiModel):
    """One pasted line the workflow could not turn into an item."""

    link: str
    """The line as pasted, trimmed."""

    reason: str
    """Operator-facing sentence explaining why it was rejected."""


class LinkBatchView(ApiModel):
    """The result of one manual-link paste."""

    workflow: str
    """Workflow that accepted the links."""

    queued: int
    """Items that now have a queued submission job."""

    skipped: int
    """Valid links left alone because the item is terminal or already has an active
    job."""

    rejected: list[RejectedLinkView]
    """Lines that could not be parsed; nothing was stored for them."""


class FieldView(ApiModel):
    """The four value slots plus lifecycle status for one editable field."""

    extracted: str | None = None
    """Value parsed from the record at extraction, in display format; ``None`` if nothing
    usable was found."""

    last_synced: str | None = None
    """Value Salesforce showed at the last read; ``None`` until a job read the page."""

    proposed: str | None = None
    """The operator's pending edit; ``None`` when nothing is pending."""

    applied: str | None = None
    """Value Salesforce accepted after a submit; ``None`` until a write succeeded."""

    status: str
    """Field lifecycle: ``extracted``, ``proposed``, ``applied`` or ``rejected``."""


class PageRefView(ApiModel):
    """One link to an SF object, with how sure extraction is of it."""

    kind: str
    """Object kind, e.g. ``opportunity`` or ``lms2_cl_contract``."""

    name: str
    """Salesforce identifier shown as the link text, e.g. ``LAI-00533155``; ``""`` when
    the object was not found."""

    url: str
    """Absolute Lightning URL; ``""`` when ``state`` is not ``found``, so the UI must not
    render a link for it."""

    state: str = "found"
    """``found`` (openable), ``absent`` (no such object) or ``unresolved`` (lookup did not
    finish)."""

    reason: str | None = None
    """Sentence explaining a non-``found`` state, e.g. "No collateral attached to this
    opportunity"; ``None`` for a found link."""


class EditView(ApiModel):
    """One row of the append-only edit audit for an item."""

    field: str
    """Catalogue key that was edited, e.g. ``loan_amount``."""

    old_value: str | None = None
    """Value before the edit (last synced, else extracted); ``None`` when nothing was known."""

    new_value: str | None = None
    """Value the operator submitted; ``None`` when they cleared it."""

    at: datetime
    """UTC timestamp the edit was recorded."""


class DecisionView(ApiModel):
    """One row of the append-only review-decision trail."""

    decision: str
    """``accept`` or ``reject``; the pending undo is never exposed as a decision row."""

    reason: str | None = None
    """Justification the operator typed, if any."""

    at: datetime
    """UTC timestamp of the decision."""


class JobView(ApiModel):
    """One queued job as the jobs table and the drawer show it."""

    id: int
    """Job row id."""

    workflow: str
    """Owning workflow, e.g. ``deviations_z02``."""

    item: str
    """Item key the job works on, e.g. ``Deviation-28102026-484106``."""

    kind: str
    """``extract`` or ``submit`` — the pipeline the job runs; the workflow is separate."""

    status: str
    """``queued``, ``running``, ``blocked_auth`` (parked until a login), ``succeeded``,
    ``failed`` or ``cancelled``."""

    phase: str | None = None
    """Submission progress (apply/validate/execute); ``None`` for other jobs."""

    attempts: int
    """How many times the job has been leased; grows when a lease expires."""

    lease_owner: str | None = None
    """Worker holding the job; ``None`` when unclaimed."""

    created_at: datetime
    """UTC timestamp the job was enqueued."""

    started_at: datetime | None = None
    """UTC timestamp of the first claim; ``None`` if it never started."""

    finished_at: datetime | None = None
    """UTC timestamp it finished; ``None`` while running."""

    duration_ms: int | None = None
    """Elapsed milliseconds, live for a running job and ``None`` for one that never
    started."""

    error: str | None = None
    """Failure message shown to the operator; ``None`` when it did not fail."""


class JobsPageView(ApiModel):
    """One page of the jobs table plus the filtered total."""

    count: int
    """Rows in this page."""

    total: int
    """Rows matching the filters across all pages."""

    rows: list[JobView]
    """This page's jobs, newest first."""


class ItemRowView(ApiModel):
    """One card/row in the review deck."""

    key: str
    """Item key, e.g. ``Deviation-28102026-484106``; the id used by every endpoint."""

    status: str
    """Work-item status, e.g. ``ready`` or ``needs_review``."""

    present: bool
    """Whether the item is still in the latest valid list refresh."""

    epoch: int
    """Presence epoch; increments when a closed item reappears."""

    record_url: str | None = None
    """Lightning URL of the deviation record; ``None`` until a refresh captured it."""

    approved_at: str | None = None
    """Approval Date exactly as the list rendered it; ``None`` when the list had none."""

    reason: str | None = None
    """Why the item is in its current status, e.g. the store's review reason."""

    fields: dict[str, FieldView]
    """Editable values keyed by catalogue key (``tenure``, ``loan_amount``, …)."""

    decision: DecisionView | None = None
    """The operator's latest accept/reject, or ``None`` while undecided."""

    active_job: JobView | None = None
    """The job currently holding this item, or ``None`` when idle."""


class ItemDetailView(ItemRowView):
    """Everything the drawer shows for one item: values, links, and audit history."""

    attributes: dict[str, str | None]
    """Read-only extracted text keyed by attribute name (``description``,
    ``product_type``, ROI keys)."""

    refs: list[PageRefView]
    """One link per declared object kind, ordered by the workflow's ``ref_kinds``."""

    edits: list[EditView]
    """Append-only edit audit, newest first."""

    decisions: list[DecisionView]
    """Every accept/reject, newest first; pending undo rows are excluded."""

    extraction_retryable: bool = False
    """Whether the Retry action may run: needs review *and* a missing link or a record
    that was never extracted."""

    extraction_job: JobView | None = None
    """The active extraction job, if one is queued or running."""


class ItemsPageView(ApiModel):
    """One page of deck rows plus the filtered total."""

    workflow: str
    """Workflow the page was filtered to."""

    count: int
    """Rows in this page."""

    total: int
    """Rows matching the filters across all pages."""

    rows: list[ItemRowView]
    """This page's items in the workflow's list order."""


class HistoryRowView(ItemRowView):
    """One approved-history row; adds the snapshot's object links."""

    refs: list[PageRefView]
    """Links as they stood when the snapshot was taken."""


class HistoryPageView(ApiModel):
    """One page of approved-history rows plus the filtered total."""

    workflow: str
    """Workflow the page was filtered to."""

    count: int
    """Rows in this page."""

    total: int
    """Rows matching the filters across all pages."""

    rows: list[HistoryRowView]
    """This page's snapshots, newest decision first."""


class JobLogsView(ApiModel):
    """A job plus the log lines it produced."""

    job: JobView
    """The job whose logs these are."""

    logs: list[str]
    """Log lines in emission order, one string per line."""


class SyncView(ApiModel):
    """The newest list refresh for a workflow, including its cross-check evidence."""

    workflow: str
    """Workflow the refresh belongs to."""

    captured_at: datetime | None = None
    """UTC timestamp the refresh finished; ``None`` when the workflow has never synced."""

    header_total: int | None = None
    """The "N items" total the list header displayed; ``None`` when it never rendered."""

    rows_read: int
    """Rows the extractor actually parsed."""

    valid: bool
    """True only when ``header_total`` was read and equals ``rows_read``."""

    warning: str | None = None
    """Why the run is invalid, e.g. "header total 42 != rows 40"; ``None`` when valid."""

    added: int
    """Items first seen in this run."""

    updated: int
    """Existing items whose listed values changed in this run."""

    closed: int
    """Items this run closed because they left the list."""


class SessionEventView(ApiModel):
    """One entry in the session's recent-event list (home page)."""

    event: str
    """Event name, e.g. ``login`` or ``expired``."""

    detail: str
    """Short human-readable detail for the operator."""

    at: datetime
    """UTC timestamp of the event."""


class SessionView(ApiModel):
    """Login/session state for the home page."""

    state: str
    """``valid``, ``expired`` (snapshot present but rejected by the org) or ``none`` (no
    snapshot saved yet)."""

    paused: bool
    """Whether the queue is parked waiting for a manual login."""

    cookies: int | None = None
    """Cookies in the stored snapshot, so a login that produced nothing is visible;
    ``None`` when no snapshot exists."""

    saved_at: datetime | None = None
    """UTC timestamp the snapshot was captured; ``None`` when there is none."""

    last_event: SessionEventView | None = None
    """The most recent session event, or ``None`` if none was recorded."""


class QueueView(ApiModel):
    """Job-queue depth and pause state."""

    concurrency: int
    """How many jobs may run at once (the configured worker count)."""

    in_flight: int
    """Jobs currently holding a lease."""

    paused: bool
    """Whether dispatch is paused waiting for a login."""

    counts: dict[str, int]
    """Job counts keyed by job status (``queued``, ``running``, ``succeeded``, …)."""


class FieldValuesBody(RootModel[dict[str, str | None]]):
    """Flat body for editable values: ``{"loan_amount": "14,50,000", "tenure": null}``."""

    root: dict[str, str | None]
    """Proposed values keyed by catalogue key; ``None`` means "clear this value"."""


class DecisionBody(ApiModel):
    """One review decision: ``{"decision": "reject", "reason": "…"}``."""

    decision: str
    """``accept`` or ``reject``."""

    reason: str | None = None
    """Optional justification stored with the decision."""


class ConcurrencyIn(ApiModel):
    """Requested worker count for the running queue."""

    concurrency: int
    """Workers to run, clamped server-side to 1..5."""


class VersionView(ApiModel):
    """The running application version (footer display)."""

    version: str
    """Version from ``app/__init__.py``, e.g. ``2.7.0``."""


class UpdateStatusView(ApiModel):
    """Update-check result (a typed projection of ``app.updater``'s payload)."""

    status: str
    """``idle``, ``up-to-date``, ``update-available``, ``disabled`` or ``failed``."""

    update_available: bool = False
    """Convenience flag for the UI: true only when a newer release was verified."""

    detail: str | None = None
    """Human-readable summary of the check, e.g. the version found."""

    error: str | None = None
    """Failure text when the check itself could not complete."""

    latest: str | None = None
    """Version string of the newest release seen, when one was found."""

    download_url: str | None = None
    """GitHub release asset URL the updater would install from."""


class NetworkView(ApiModel):
    """Server address information shown on the home page."""

    host: str
    """Bind interface the server was started with, e.g. ``0.0.0.0``."""

    port: int
    """TCP port the server listens on."""

    lan_ip: str | None = None
    """Best-guess LAN address of this machine, or ``None`` when it could not be determined."""

    lan_url: str | None = None
    """``http://<lan_ip>:<port>`` for other devices, or ``None`` without a LAN IP."""

    local_url: str
    """``http://127.0.0.1:<port>`` for this machine."""

    lan_enabled: bool
    """Whether the bind address actually exposes the server beyond loopback."""


class TimeoutPresetView(ApiModel):
    """One selectable network profile and the budgets it produces, in seconds."""

    profile: NetworkProfile
    """``fast``, ``default`` or ``slow``."""

    action_s: int
    """Budget for one browser action or wait; never below 60."""

    stage_read_s: int
    """Budget for reading all targets on one object."""

    stage_write_s: int
    """Budget for writing all targets on one object."""

    submission_s: int
    """Whole-run budget for one submission or extraction."""


class SettingsView(ApiModel):
    """The network profile in force and every preset the dialog offers."""

    profile: NetworkProfile
    """Profile applied to the next job; a change is live, no restart needed."""

    presets: list[TimeoutPresetView]
    """All three profiles with their derived budgets, computed server-side so the UI
    never does arithmetic."""


class SettingsBody(ApiModel):
    """Request body for ``PATCH /api/settings``."""

    profile: NetworkProfile
    """Profile to apply and persist; an unknown value is a 422 from the enum."""


#: One scalar cell in a dev query result. SQLite blobs are converted to placeholders.
DevCell = str | int | float | None


class DevTableView(ApiModel):
    """One table in the dev explorer list."""

    name: str
    """SQLite table name; the sessions table is never included."""

    rows: int
    """Approximate row count, for the explorer's overview."""

    columns: list[str]
    """Column names in declaration order."""


class DevTablesView(ApiModel):
    """The tables a dev explorer may query; the token table is never listed."""

    tables: list[DevTableView]
    """Queryable tables in alphabetical order."""


class DevQueryIn(ApiModel):
    """One read-only SQL statement and the preview row cap."""

    sql: str
    """A single ``SELECT`` statement; anything that writes is refused before execution."""

    limit: int = Field(default=500, ge=1, le=5_000)
    """Maximum rows the preview returns (1..5000)."""


class DevQueryView(ApiModel):
    """Bounded read-only result for the preview table."""

    columns: list[str]
    """Result column names in query order."""

    rows: list[list[DevCell]]
    """Result rows as scalars; SQLite blobs appear as placeholders, never raw bytes."""

    row_count: int
    """Rows returned in ``rows``."""

    truncated: bool
    """True when the query produced more rows than ``limit``."""

    duration_ms: int
    """Wall-clock milliseconds the statement took, bounded by the explorer's timeout."""


class DevExportIn(ApiModel):
    """Export the same read-only query as CSV or a real Excel workbook."""

    sql: str
    """The same single read-only statement accepted by the preview."""

    format: Literal["csv", "xlsx"]
    """Output format written to the download."""


class PurgeIn(ApiModel):
    """One manual retention action; the server owns the cutoff."""

    scope: Literal["current", "history"]
    """Which store to purge: ``current`` work items (24 h) or ``history`` snapshots
    (90 days)."""

    dry_run: bool = False
    """Preview counts without deleting; the UI always sends one dry run first."""


class PurgeView(ApiModel):
    """Per-table result of a dry-run or real purge."""

    scope: Literal["current", "history"]
    """The store the action applied to."""

    cutoff: datetime
    """UTC cutoff the server fixed for this run; older rows are eligible."""

    dry_run: bool
    """Whether this result is a preview (``deleted`` counts are what *would* go)."""

    deleted: dict[str, int]
    """Rows affected per table name, e.g. ``{"work_items": 12, "jobs": 30}``."""

    total: int
    """Sum of ``deleted`` across tables."""
