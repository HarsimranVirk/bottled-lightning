"""Services behind the HTTP surface: item operations and admin actions.

Routes stay one-liners; every rule (editable status, value normalisation, single active
job, auth pause) lives here so it can be unit-tested without an HTTP client.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from app import config, updater
from app.config import Settings
from app.core.errors import SessionExpired
from app.core.field import normalise
from app.core.models import (
    ApprovedDeviation,
    Decision,
    FieldValue,
    Job,
    PageRef,
    WorkItem,
    job_duration_ms,
    utcnow,
)
from app.core.registry import WorkflowRegistry
from app.core.repo.approved_history import ApprovedHistoryRepository, HistoryQuery
from app.core.repo.attributes import AttributeRepository
from app.core.repo.decisions import DecisionRepository
from app.core.repo.edits import EditRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.jobs import JOB_SORT_COLUMNS, JobPage, JobQuery, JobRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.sync_runs import SyncRunRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import (
    DecisionFilter,
    DecisionKind,
    JobKind,
    JobStatus,
    Phase,
    WorkItemStatus,
)
from app.core.workflow import Workflow
from app.jobs.auth import AuthGate
from app.jobs.dispatcher import Dispatcher
from app.pipeline.watcher import ListWatcher
from app.salesforce.login import run_login
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider
from app.utils.json import JsonValue
from app.utils.network import is_loopback_host, lan_ip

from .errors import ApiError
from .schemas import (
    DecisionView,
    EditView,
    FieldView,
    HistoryPageView,
    HistoryRowView,
    ItemDetailView,
    ItemRowView,
    ItemsPageView,
    JobLogsView,
    JobsPageView,
    JobView,
    NetworkView,
    PageRefView,
    QueueView,
    SessionEventView,
    SessionView,
    SyncView,
    UpdateStatusView,
    WorkflowFieldView,
    WorkflowView,
)

_EDITABLE = frozenset(
    {WorkItemStatus.READY, WorkItemStatus.EDITING, WorkItemStatus.NEEDS_REVIEW}
)
_SUBMITTABLE = _EDITABLE
_TERMINAL = frozenset(
    {WorkItemStatus.COMPLETED, WorkItemStatus.CLOSED, WorkItemStatus.SKIPPED}
)
logger = logging.getLogger(__name__)


def workflow_view(workflow: Workflow) -> WorkflowView:
    """Project a registered workflow into its public description."""
    return WorkflowView(
        name=workflow.name,
        route=workflow.route,
        label=workflow.name.replace("_", " ").title(),
        list_url=workflow.list_view.url,
        ref_kinds=list(workflow.ref_kinds),
        fields=[
            WorkflowFieldView(
                key=field.key,
                label=field.label,
                value_type=field.value_type.value,
                required=field.required,
                targets=[target.object_kind for target in field.targets],
            )
            for field in workflow.catalog
        ],
        terminal_labels={status.value: label for status, label in workflow.terminal_labels.items()},
    )


def job_view(job: Job) -> JobView:
    """Project a job row into its public shape."""
    return JobView(
        id=job.id,
        workflow=job.workflow,
        item=job.item,
        kind=job.kind.value,
        status=job.status.value,
        phase=job.phase.value if job.phase is not None else None,
        attempts=job.attempts,
        lease_owner=job.lease_owner,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_ms=job_duration_ms(job, utcnow()),
        error=job.error,
    )


def decision_view(decision: Decision) -> DecisionView:
    """Project a stored decision into its public shape."""
    return DecisionView(
        decision=decision.decision.value,
        reason=decision.reason,
        at=decision.created_at,
    )


def update_block_reason(
    *,
    login_running: bool,
    job_counts: Mapping[str, int],
    source_checkout: bool,
    allow_source: bool,
) -> str | None:
    """Why an update must not install right now, or ``None`` when it is safe."""
    if login_running:
        return "manual login in progress"
    active = (
        job_counts.get("queued", 0)
        + job_counts.get("running", 0)
        + job_counts.get("blocked_auth", 0)
    )
    if active > 0:
        return "jobs are running"
    if source_checkout and not allow_source:
        return "source checkout (SF_UPDATE_ALLOW_SOURCE=1 to allow)"
    return None


def update_status_view(payload: Mapping[str, JsonValue]) -> UpdateStatusView:
    """Project the updater's loose payload onto the documented DTO."""

    def text(key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) else None

    return UpdateStatusView(
        status=text("status") or "unknown",
        update_available=bool(payload.get("update_available")),
        detail=text("detail"),
        error=text("error"),
        latest=text("latest"),
        download_url=text("download_url"),
    )


class WorkItemService:
    """Reads and edits one workflow's items; enqueues submissions.

    Synchronous and database-only: it never touches Playwright, so routes can call it
    from FastAPI's threadpool.
    """

    def __init__(
        self,
        registry: WorkflowRegistry,
        items: WorkItemRepository,
        fields: FieldValueRepository,
        attributes: AttributeRepository,
        refs: PageRefRepository,
        edits: EditRepository,
        decisions: DecisionRepository,
        jobs: JobRepository,
        events: EventRepository,
        is_paused: Callable[[], bool],
        history: ApprovedHistoryRepository | None = None,
    ) -> None:
        self._registry = registry
        self._items = items
        self._fields = fields
        self._attributes = attributes
        self._refs = refs
        self._edits = edits
        self._decisions = decisions
        self._jobs = jobs
        self._events = events
        self._is_paused = is_paused
        self._history = history

    # -- reads -------------------------------------------------------------
    def list_workflows(self) -> list[WorkflowView]:
        """Every registered workflow, with its editable-field catalogue."""
        return [workflow_view(workflow) for workflow in self._registry.all()]

    def list_items(
        self,
        workflow_name: str,
        statuses: Sequence[str] | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
        decision: str | None = None,
        sort: str = "last_seen",
        order: str = "desc",
    ) -> ItemsPageView:
        """The unified view: one row per item, newest-seen first.

        ``statuses`` is the repeated ``?status=`` filter (the deck asks for every
        decidable status at once); ``decision`` filters on the newest review decision.
        Decisions for the page are fetched in one query, not per row.
        """
        workflow = self._workflow(workflow_name)
        parsed = (
            [self._parse_status(status) for status in statuses] if statuses else None
        )
        parsed_decision = self._parse_decision(decision)
        if sort not in {"last_seen", "decision"}:
            raise ApiError(422, f"unknown sort: {sort}", "invalid_sort")
        direction = order.lower()
        if direction not in {"asc", "desc"}:
            raise ApiError(422, f"unknown order: {order}", "invalid_order")
        items, total = self._items.list(
            workflow.name,
            parsed,
            query,
            limit,
            offset,
            decision=parsed_decision,
            sort=sort,
            order=direction,
        )
        decisions = self._decisions.latest_for(
            workflow.name, [item.key for item in items]
        )
        return ItemsPageView(
            workflow=workflow.name,
            count=len(items),
            total=total,
            rows=[
                self._row_view(workflow, item, decisions.get(item.key)) for item in items
            ],
        )

    def get_item(self, workflow_name: str, key: str) -> ItemDetailView:
        """One item with read-only attributes, object links and edit history."""
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        return self._detail_view(workflow, item)

    def list_history(
        self,
        workflow_name: str,
        query: HistoryQuery | None = None,
    ) -> HistoryPageView:
        """
        Page the approved-history snapshots, newest accept first.

        Reads only the segregated snapshot store, so a purged work item cannot remove a
        row from this response. The caller supplies the standard filter row; ``None``
        means no filters and the first 25 rows. Object links for the whole page are read
        once, not per row.
        """
        workflow = self._workflow(workflow_name)
        if self._history is None:
            return HistoryPageView(
                workflow=workflow.name, count=0, total=0, rows=[]
            )
        items, total = self._history.page(workflow.name, query or HistoryQuery())
        refs_by_key = self._history.refs_for(workflow.name, [item.key for item in items])
        return HistoryPageView(
            workflow=workflow.name,
            count=len(items),
            total=total,
            rows=[
                self._history_list_row_view(
                    workflow,
                    item,
                    self._history.fields(workflow.name, item.key),
                    refs_by_key.get(item.key, {}),
                )
                for item in items
            ],
        )

    def get_history_item(self, workflow_name: str, key: str) -> ItemDetailView:
        """One history snapshot with its read-only attributes, refs and edit audit."""
        workflow = self._workflow(workflow_name)
        if self._history is None:
            raise ApiError(404, f"unknown history item: {key}", "unknown_history_item")
        item = self._history.get(workflow.name, key)
        if item is None:
            raise ApiError(404, f"unknown history item: {key}", "unknown_history_item")
        return self._history_detail_view(workflow, item)

    # -- writes ------------------------------------------------------------
    def patch_fields(
        self, workflow_name: str, key: str, changes: Mapping[str, str | None]
    ) -> ItemDetailView:
        """Propose editable values; ``None`` or an empty string discards a proposal.

        An empty/whitespace value means “no update”, not “write an empty value”: the
        operator clearing an input must never send an empty amount to Salesforce. Values
        are canonicalised with the field's ``ValueType``; an unparseable non-empty value
        is rejected with 422 before anything is stored.
        """
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        self._ensure_status(item, _EDITABLE, "editable")

        normalised: dict[str, str | None] = {}
        for field_key, value in changes.items():
            spec = next((f for f in workflow.catalog if f.key == field_key), None)
            if spec is None:
                raise ApiError(422, f"unknown field: {field_key}", "unknown_field")
            if value is None or not value.strip():
                normalised[field_key] = None
                continue
            try:
                normalised[field_key] = normalise(value, spec.value_type)
            except ValueError as exc:
                raise ApiError(
                    422, f"{field_key}: {exc}", "invalid_value"
                ) from exc

        self._fields.propose(workflow.name, key, normalised)
        if item.status is not WorkItemStatus.EDITING:
            # NEEDS_REVIEW cannot go straight to EDITING; it recovers through READY.
            if item.status is WorkItemStatus.NEEDS_REVIEW:
                self._items.transition(workflow.name, key, WorkItemStatus.READY)
            self._items.transition(workflow.name, key, WorkItemStatus.EDITING)
            self._events.emit("edited", workflow=workflow.name, item=key)
        return self._detail_view(workflow, self._item(workflow, key))

    def discard_fields(self, workflow_name: str, key: str) -> ItemDetailView:
        """Drop every pending proposal and return the item to ``ready``."""
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        self._ensure_status(item, _EDITABLE, "editable")
        self._fields.discard_proposed(workflow.name, key)
        if item.status is WorkItemStatus.EDITING:
            self._items.transition(workflow.name, key, WorkItemStatus.READY)
        return self._detail_view(workflow, self._item(workflow, key))

    def decide(
        self,
        workflow_name: str,
        key: str,
        decision: str,
        reason: str | None = None,
    ) -> ItemDetailView:
        """Record an accept/reject review decision (FR-10).

        A decision is local and reversible: it writes no Salesforce data and leaves the
        item's pipeline status untouched. Only the three decidable statuses are allowed,
        so an in-flight or terminal item cannot be re-decided.
        """
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        self._ensure_status(item, _EDITABLE, "decidable")

        try:
            kind = DecisionKind(decision)
        except ValueError as exc:
            raise ApiError(
                422, f"unknown decision: {decision}", "invalid_decision"
            ) from exc
        if kind is DecisionKind.PENDING:
            raise ApiError(422, "record accept or reject", "invalid_decision")

        note = reason.strip() if reason is not None else None
        at = utcnow()
        self._decisions.record(workflow.name, key, kind, note or None, at)
        if self._history is not None:
            if kind is DecisionKind.ACCEPT:
                self._history.record_accept(workflow.name, key, note or None, at)
            else:
                self._history.remove(workflow.name, key)
        self._events.emit(
            kind.value,
            workflow=workflow.name,
            item=key,
            detail=note or None,
        )
        return self._detail_view(workflow, self._item(workflow, key))

    def undo_decision(self, workflow_name: str, key: str) -> ItemDetailView:
        """Return a decided item to undecided; the audit keeps both rows (FR-10.3)."""
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        self._ensure_status(item, _EDITABLE, "decidable")

        current = self._decisions.latest(workflow.name, key)
        if current is None or current.decision is DecisionKind.PENDING:
            raise ApiError(409, "no decision to undo", "no_decision")

        self._decisions.record(
            workflow.name, key, DecisionKind.PENDING, None, utcnow()
        )
        if self._history is not None:
            self._history.remove(workflow.name, key)
        self._events.emit("decision_cleared", workflow=workflow.name, item=key)
        return self._detail_view(workflow, self._item(workflow, key))

    def submit(self, workflow_name: str, key: str) -> JobView:
        """Enqueue exactly one ``SUBMIT`` job for an item that has proposed values."""
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        self._ensure_status(item, _SUBMITTABLE, "submittable")

        if self._is_paused():
            raise ApiError(409, "manual login required", "login_required")

        stored = self._fields.for_item(workflow.name, key)
        proposed = {
            field.key: field
            for field in stored.values()
            if field.proposed is not None and field.proposed.strip()
        }
        if not proposed:
            raise ApiError(422, "no proposed values to submit", "nothing_to_submit")

        if self._jobs.active_for(workflow.name, key) is not None:
            raise ApiError(409, "an active job already exists for this item", "job_active")

        job = self._jobs.enqueue(workflow.name, JobKind.SUBMIT, key)
        self._items.transition(workflow.name, key, WorkItemStatus.SUBMITTING)
        submitted_at = utcnow()
        for field_key, field in sorted(proposed.items()):
            # FR-5.3: the audit is written when the operator submits, so the old value
            # (what the edit was based on) and the proposed value are both recorded
            # even if the job later fails before writing.
            self._edits.record(
                workflow.name,
                key,
                field_key,
                field.last_synced or field.extracted,
                field.proposed,
                submitted_at,
                job.id,
            )
        if self._history is not None:
            try:
                self._history.refresh(workflow.name, key)
            except Exception:
                logger.exception(
                    "approved-history refresh failed for %s/%s",
                    workflow.name,
                    key,
                )
        self._events.emit(
            "submitted", workflow=workflow.name, item=key, job_id=job.id
        )
        return job_view(job)

    # -- helpers -----------------------------------------------------------
    def _workflow(self, name: str) -> Workflow:
        try:
            return self._registry.get(name)
        except Exception as exc:
            raise ApiError(404, f"unknown workflow: {name}", "unknown_workflow") from exc

    def _item(self, workflow: Workflow, key: str) -> WorkItem:
        item = self._items.get(workflow.name, key)
        if item is None:
            raise ApiError(404, f"unknown item: {key}", "unknown_item")
        return item

    def _parse_decision(self, decision: str | None) -> DecisionFilter | None:
        """Parse the ``?decision=`` filter, or ``None`` for any decision."""
        if not decision:
            return None
        try:
            return DecisionFilter(decision)
        except ValueError as exc:
            raise ApiError(
                422, f"unknown decision filter: {decision}", "invalid_decision"
            ) from exc

    def _parse_status(self, status: str) -> WorkItemStatus:
        try:
            return WorkItemStatus(status)
        except ValueError as exc:
            raise ApiError(422, f"unknown status: {status}", "invalid_status") from exc

    def _ensure_status(
        self, item: WorkItem, allowed: frozenset[WorkItemStatus], action: str
    ) -> None:
        if item.status not in allowed:
            raise ApiError(
                409,
                f"item is {item.status.value} and not {action}",
                "invalid_state",
            )

    def _row_view(
        self,
        workflow: Workflow,
        item: WorkItem,
        decision: Decision | None = None,
    ) -> ItemRowView:
        active = self._jobs.active_for(workflow.name, item.key)
        return ItemRowView(
            key=item.key,
            status=item.status.value,
            present=item.present,
            epoch=item.epoch,
            record_url=item.record_url,
            approved_at=item.approved_at,
            reason=item.reason,
            fields=self._field_views(
                workflow, self._fields.for_item(workflow.name, item.key)
            ),
            decision=(
                decision_view(decision) if decision is not None else None
            ),
            active_job=job_view(active) if active is not None else None,
        )

    def _history_row_view(
        self,
        workflow: Workflow,
        item: ApprovedDeviation,
        stored: Mapping[str, FieldValue],
    ) -> ItemRowView:
        """Project one snapshot parent into the same row shape as the current list."""
        return ItemRowView(
            key=item.key,
            status=item.status.value,
            present=item.present,
            epoch=item.epoch,
            record_url=item.record_url,
            approved_at=item.approved_at,
            reason=item.reason,
            fields=self._field_views(workflow, stored),
            decision=DecisionView(
                decision=DecisionKind.ACCEPT.value,
                reason=item.decision_reason,
                at=item.decided_at,
            ),
            active_job=None,
        )

    def _history_list_row_view(
        self,
        workflow: Workflow,
        item: ApprovedDeviation,
        stored: Mapping[str, FieldValue],
        refs: Mapping[str, PageRef],
    ) -> HistoryRowView:
        """
        Add the snapshot's object links to a list row.

        Refs are ordered by the workflow's ``ref_kinds`` so a column never changes
        position between pages. Kinds with no stored ref are omitted; the UI renders a
        dash for them.
        """
        base = self._history_row_view(workflow, item, stored)
        return HistoryRowView(
            **base.model_dump(),
            refs=[
                PageRefView(
                    kind=refs[kind].kind,
                    name=refs[kind].name,
                    url=refs[kind].url,
                )
                for kind in workflow.ref_kinds
                if kind in refs
            ],
        )

    def _history_detail_view(
        self, workflow: Workflow, item: ApprovedDeviation
    ) -> ItemDetailView:
        """Project a snapshot parent and its children into the current detail shape."""
        if self._history is None:
            raise ApiError(
                404, f"unknown history item: {item.key}", "unknown_history_item"
            )
        row = self._history_row_view(
            workflow, item, self._history.fields(workflow.name, item.key)
        )
        refs = self._history.refs(workflow.name, item.key)
        edits = self._history.edits(workflow.name, item.key)
        return ItemDetailView(
            **row.model_dump(),
            attributes=self._history.attributes(workflow.name, item.key),
            refs=[
                PageRefView(kind=ref.kind, name=ref.name, url=ref.url)
                for ref in refs.values()
            ],
            edits=[
                EditView(
                    field=field,
                    old_value=old,
                    new_value=new,
                    at=datetime.fromisoformat(at),
                )
                for field, old, new, at in edits
            ],
            decisions=[
                DecisionView(
                    decision=DecisionKind.ACCEPT.value,
                    reason=item.decision_reason,
                    at=item.decided_at,
                )
            ],
        )

    def _field_views(
        self, workflow: Workflow, stored: Mapping[str, FieldValue]
    ) -> dict[str, FieldView]:
        """Build one view per catalogue field, including fields with no stored row."""
        fields: dict[str, FieldView] = {}
        for spec in workflow.catalog:
            value = stored.get(spec.key)
            fields[spec.key] = (
                FieldView(
                    extracted=value.extracted,
                    last_synced=value.last_synced,
                    proposed=value.proposed,
                    applied=value.applied,
                    status=value.status.value,
                )
                if value is not None
                else FieldView(extracted=None, status="extracted")
            )
        return fields

    def _detail_view(self, workflow: Workflow, item: WorkItem) -> ItemDetailView:
        latest = self._decisions.latest(workflow.name, item.key)
        if latest is not None and latest.decision is DecisionKind.PENDING:
            latest = None
        row = self._row_view(workflow, item, latest)
        refs = self._refs.for_item(workflow.name, item.key)
        edits = self._edits.for_item(workflow.name, item.key)
        decisions = self._decisions.history(workflow.name, item.key)
        return ItemDetailView(
            **row.model_dump(),
            attributes=self._attributes.for_item(workflow.name, item.key),
            refs=[
                PageRefView(kind=ref.kind, name=ref.name, url=ref.url)
                for ref in refs.values()
            ],
            edits=[
                EditView(
                    field=field,
                    old_value=old,
                    new_value=new,
                    at=datetime.fromisoformat(at),
                )
                for field, old, new, at in edits
            ],
            decisions=[
                decision_view(decision)
                for decision in decisions
                if decision.decision is not DecisionKind.PENDING
            ],
        )


class AdminPort(Protocol):
    """Everything the admin routes need, so tests can substitute a fake."""

    def session(self) -> SessionView: ...

    def login(self) -> SessionView: ...

    def logout(self) -> None: ...

    def latest_sync(self, workflow: str) -> SyncView | None: ...

    def request_sync(self, workflow: str) -> None: ...

    def queue(self) -> QueueView: ...

    def set_concurrency(self, concurrency: int) -> QueueView: ...

    def network(self) -> NetworkView: ...

    def update_status(self) -> UpdateStatusView: ...

    def install_update(self, *, auto: bool = False) -> UpdateStatusView: ...

    def jobs(
        self,
        workflow: str | None = None,
        kind: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        phase: Sequence[str] | None = None,
        status_text: str | None = None,
        kind_text: str | None = None,
        phase_text: str | None = None,
        item: str | None = None,
        item_in: Sequence[str] | None = None,
        job_id: str | None = None,
        id_in: Sequence[str] | None = None,
        error: str | None = None,
        error_in: Sequence[str] | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        duration_min_ms: int | None = None,
        duration_max_ms: int | None = None,
        sort: str = 'id',
        order: str = 'desc',
        limit: int = 25,
        offset: int = 0,
    ) -> JobsPageView: ...

    def job_logs(self, job_id: int) -> JobLogsView: ...

    def cancel_job(self, job_id: int) -> None: ...


class AdminService:
    """Session, queue and job administration over the live runtime.

    Actions that touch Playwright (login, forced sync, worker count) are spawned on the
    browser loop; reads are plain repository calls safe from any thread.
    """

    def __init__(
        self,
        settings: Settings,
        runtime: BrowserRuntime,
        provider: SessionProvider,
        sessions: SessionRepository,
        sync_runs: SyncRunRepository,
        jobs: JobRepository,
        auth: AuthGate,
        dispatcher: Dispatcher,
        watchers: Mapping[str, ListWatcher],
        registry: WorkflowRegistry,
    ) -> None:
        self._settings = settings
        self._runtime = runtime
        self._provider = provider
        self._sessions = sessions
        self._sync_runs = sync_runs
        self._jobs = jobs
        self._auth = auth
        self._dispatcher = dispatcher
        self._watchers = watchers
        self._registry = registry
        self._install_lock = threading.Lock()
        self._login_running = threading.Event()
        self._auto_attempted: str | None = None
        self._auto_started = False

    def session(self) -> SessionView:
        snapshot = self._sessions.snapshot()
        event = self._sessions.last_event()
        state = "none"
        if snapshot is not None:
            state = "expired" if self._provider.expired else "valid"
        return SessionView(
            state=state,
            paused=self._auth.paused,
            cookies=snapshot.cookie_count if snapshot is not None else None,
            saved_at=snapshot.created_at if snapshot is not None else None,
            last_event=(
                SessionEventView(event=event[0], detail=event[1], at=event[2])
                if event is not None
                else None
            ),
        )

    def login(self) -> SessionView:
        if self._provider.snapshot is not None and not self._provider.expired:
            return self.session()

        async def _login() -> None:
            self._login_running.set()
            try:
                ok = await run_login(self._settings, self._sessions, reset=False)
                if ok:
                    await self._provider.reload(self._runtime.context)
                    self._auth.resume()
            finally:
                self._login_running.clear()

        self._runtime.spawn(_login)
        return self.session()

    def logout(self) -> None:
        self._sessions.clear()
        self._sessions.event("logout", "session cleared")
        self._auth.pause("session cleared")

    def latest_sync(self, workflow: str) -> SyncView | None:
        run = self._sync_runs.latest(self._workflow_name(workflow))
        if run is None:
            return None
        return SyncView(
            workflow=run.workflow,
            captured_at=run.captured_at,
            header_total=run.header_total,
            rows_read=run.rows_read,
            valid=run.valid,
            warning=run.warning,
            added=run.added,
            updated=run.updated,
            closed=run.closed,
        )

    def request_sync(self, workflow: str) -> None:
        """Request one immediate refresh of a workflow's list view (FR-2.10, FR-2.13).

        Raises ``ApiError`` 404 for an unknown workflow and 409 ``login_required``
        when the refresh is already known to be impossible. Otherwise one cycle is
        spawned on the browser loop and the caller returns immediately (``202``);
        that cycle opens the page itself when it is not open yet.

        Example:
            admin.request_sync("deviations_z02")   # 202, work happens on the loop
        """
        name = self._workflow_name(workflow)
        watcher = self._watchers.get(name)
        if watcher is None:
            raise ApiError(404, f"no watcher for {name}", "unknown_workflow")
        self._require_session()

        async def _once() -> None:
            try:
                await watcher.refresh_once()
            except SessionExpired as exc:
                # A snapshot that only looked valid: park the system instead of
                # letting the fire-and-forget task die silently (FR-2.13).
                self._auth.pause(f"sync: {exc}")
            except Exception:
                logger.exception("manual refresh failed for %s", name)

        self._runtime.spawn(_once)

    def _require_session(self) -> None:
        """Refuse work when a manual login is already known to be required (FR-2.13).

        Uses the same three signals ``session()`` reports: no stored snapshot, a
        snapshot the last SF interaction marked expired, or a paused gate. A
        snapshot that merely *looks* valid is not refused here — its cycle pauses
        the gate and surfaces through ``GET /api/sessions`` instead.
        """
        if (
            self._sessions.snapshot() is None
            or self._provider.expired
            or self._auth.paused
        ):
            raise ApiError(409, "manual login required", "login_required")

    def queue(self) -> QueueView:
        counts = self._jobs.counts()
        return QueueView(
            concurrency=self._dispatcher.concurrency,
            in_flight=self._dispatcher.in_flight,
            paused=self._auth.paused,
            counts=counts,
        )

    def set_concurrency(self, concurrency: int) -> QueueView:
        if not 1 <= concurrency <= 5:
            raise ApiError(422, "concurrency must be between 1 and 5", "invalid_value")

        async def _set() -> None:
            self._dispatcher.set_concurrency(concurrency)

        self._runtime.spawn(_set)
        return self.queue()

    def jobs(
        self,
        workflow: str | None = None,
        kind: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        phase: Sequence[str] | None = None,
        status_text: str | None = None,
        kind_text: str | None = None,
        phase_text: str | None = None,
        item: str | None = None,
        item_in: Sequence[str] | None = None,
        job_id: str | None = None,
        id_in: Sequence[str] | None = None,
        error: str | None = None,
        error_in: Sequence[str] | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        duration_min_ms: int | None = None,
        duration_max_ms: int | None = None,
        sort: str = 'id',
        order: str = 'desc',
        limit: int = 25,
        offset: int = 0,
    ) -> JobsPageView:
        """One filtered, sorted page of the jobs table (FR-7.10/7.11)."""
        page: JobPage = self._jobs.query(
            JobQuery(
                workflow=workflow,
                kinds=tuple(self._required_kind(value) for value in kind or ()),
                statuses=tuple(
                    self._required_job_status(value) for value in status or ()
                ),
                phases=tuple(self._required_phase(value) for value in phase or ()),
                status_text=self._text(status_text),
                kind_text=self._text(kind_text),
                phase_text=self._text(phase_text),
                item=self._text(item),
                items_in=self._texts(item_in),
                job_id=self._text(job_id),
                job_ids_in=self._texts(id_in),
                error=self._text(error),
                errors_in=self._texts(error_in),
                started_after=self._text(started_after),
                started_before=self._text(started_before),
                duration_min_ms=duration_min_ms,
                duration_max_ms=duration_max_ms,
                sort=self._sort(sort),
                order=self._order(order),
                limit=limit,
                offset=offset,
            )
        )
        return JobsPageView(
            count=len(page.jobs),
            total=page.total,
            rows=[job_view(job) for job in page.jobs],
        )

    def job_logs(self, job_id: int) -> JobLogsView:
        job = self._jobs.get(job_id)
        if job is None:
            raise ApiError(404, f"unknown job {job_id}", "unknown_job")
        return JobLogsView(job=job_view(job), logs=self._jobs.logs(job_id))

    def cancel_job(self, job_id: int) -> None:
        if not self._jobs.cancel(job_id):
            raise ApiError(409, f"job {job_id} is not queued", "job_not_queued")

    # -- network and updates ------------------------------------------------
    def network(self) -> NetworkView:
        """Addresses the home page shows for this and other devices."""
        host = self._settings.host
        port = self._settings.port
        ip = lan_ip()
        enabled = not is_loopback_host(host) and ip is not None
        return NetworkView(
            host=host,
            port=port,
            lan_ip=ip,
            lan_url=f"http://{ip}:{port}" if enabled and ip is not None else None,
            local_url=f"http://127.0.0.1:{port}",
            lan_enabled=enabled,
        )

    def update_status(self) -> UpdateStatusView:
        """The last update-check or install result."""
        return update_status_view(updater.status())

    def install_update(self, *, auto: bool = False) -> UpdateStatusView:
        """
        Start installing the pending release, or explain why it cannot.

        Manual calls raise ``409`` with the blocking reason; the background auto loop
        instead leaves the status untouched and retries later. The install itself runs
        in a daemon thread, so the request returns ``202`` and the status reads
        ``installing`` before pip starts.
        """
        result = updater.check_for_update(force=not auto)
        latest = result.get("latest")
        version = latest if isinstance(latest, str) else ""
        if auto and version and version == self._auto_attempted:
            return self.update_status()
        if not bool(result.get("update_available")):
            return self.update_status()

        reason = self._update_block_reason()
        if reason is not None:
            if auto:
                return self.update_status()
            raise ApiError(409, reason, "update_blocked")
        if not self._install_lock.acquire(blocking=False):
            if auto:
                return self.update_status()
            raise ApiError(409, "install already running", "update_in_progress")
        if auto and version:
            self._auto_attempted = version
        updater.mark_installing(version or "update")
        threading.Thread(
            target=self._run_install,
            name="sf-update-install",
            daemon=True,
        ).start()
        return self.update_status()

    def start_auto_update(self) -> None:
        """Start the background auto-install loop when policy and config allow it."""
        if self._auto_started:
            return
        self._auto_started = True
        if not config.UPDATE_AUTO_START or self._settings.update_policy != "auto":
            return
        threading.Thread(
            target=self._auto_update_loop, name="sf-auto-update", daemon=True
        ).start()

    def _auto_update_loop(self) -> None:
        """Check after boot, then every ten minutes, installing only when idle."""
        time.sleep(20)
        while True:
            try:
                self.install_update(auto=True)
            except Exception:
                logger.exception("automatic update check failed")
            time.sleep(600)

    def _run_install(self) -> None:
        """Install in the background; release the lock whatever the outcome."""
        try:
            updater.apply_pending(
                guard=self._update_block_reason,
                stop=self._stop_for_restart,
            )
        finally:
            self._install_lock.release()

    def _update_block_reason(self) -> str | None:
        """Why an install must not start now, or ``None`` when it is safe."""
        return update_block_reason(
            login_running=self._login_running.is_set(),
            job_counts=self._jobs.counts(),
            source_checkout=config.IS_SOURCE_CHECKOUT,
            allow_source=config.UPDATE_ALLOW_SOURCE,
        )

    def _stop_for_restart(self) -> None:
        """Close the browser before the updater replaces the process."""
        try:
            self._runtime.stop()
        except Exception:
            logger.exception("stopping the browser before restart failed")

    def _text(self, value: str | None) -> str | None:
        """Trim an optional query string; blank means no filter."""
        return value.strip() or None if value is not None else None

    def _texts(self, values: Sequence[str] | None) -> tuple[str, ...]:
        """Trim repeated query values, dropping blanks, for an exact-value filter."""
        return tuple(
            text for value in values or () if (text := value.strip()) != ""
        )

    def _phase(self, phase: str | None) -> Phase | None:
        if not phase:
            return None
        try:
            return Phase(phase)
        except ValueError as exc:
            raise ApiError(422, f"unknown phase: {phase}", "invalid_value") from exc

    def _sort(self, sort: str) -> str:
        if sort not in JOB_SORT_COLUMNS:
            raise ApiError(422, f"unknown sort: {sort}", "invalid_value")
        return sort

    def _order(self, order: str) -> str:
        normalised = order.lower()
        if normalised not in {"asc", "desc"}:
            raise ApiError(422, f"unknown order: {order}", "invalid_value")
        return normalised

    def _workflow_name(self, workflow: str) -> str:
        try:
            return self._registry.get(workflow).name
        except Exception as exc:
            raise ApiError(404, f"unknown workflow: {workflow}", "unknown_workflow") from exc

    def _required_kind(self, kind: str) -> JobKind:
        """Parse a repeated kind value, which is never ``None``."""
        parsed = self._kind(kind)
        if parsed is None:
            raise ApiError(422, "kind must not be empty", "invalid_value")
        return parsed

    def _required_job_status(self, status: str) -> JobStatus:
        """Parse a repeated status value, which is never ``None``."""
        parsed = self._job_status(status)
        if parsed is None:
            raise ApiError(422, "status must not be empty", "invalid_value")
        return parsed

    def _required_phase(self, phase: str) -> Phase:
        """Parse a repeated phase value, which is never ``None``."""
        parsed = self._phase(phase)
        if parsed is None:
            raise ApiError(422, "phase must not be empty", "invalid_value")
        return parsed

    def _kind(self, kind: str | None) -> JobKind | None:
        if kind is None:
            return None
        try:
            return JobKind(kind)
        except ValueError as exc:
            raise ApiError(422, f"unknown kind: {kind}", "invalid_value") from exc

    def _job_status(self, status: str | None) -> JobStatus | None:
        if status is None:
            return None
        try:
            return JobStatus(status)
        except ValueError as exc:
            raise ApiError(422, f"unknown job status: {status}", "invalid_value") from exc
