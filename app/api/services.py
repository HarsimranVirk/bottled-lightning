"""Services behind the HTTP surface: item operations and admin actions.

Routes stay one-liners; every rule (editable status, value normalisation, single active
job, auth pause) lives here so it can be unit-tested without an HTTP client.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

from app.config import Settings
from app.core.field import normalise
from app.core.models import Job, WorkItem
from app.core.registry import WorkflowRegistry
from app.core.repo.attributes import AttributeRepository
from app.core.repo.edits import EditRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.sync_runs import SyncRunRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import JobKind, JobStatus, WorkItemStatus
from app.core.workflow import Workflow
from app.jobs.auth import AuthGate
from app.jobs.dispatcher import Dispatcher
from app.pipeline.watcher import ListWatcher
from app.salesforce.login import run_login
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider

from .errors import ApiError
from .schemas import (
    EditView,
    FieldView,
    ItemDetailView,
    ItemRowView,
    ItemsPageView,
    JobLogsView,
    JobView,
    PageRefView,
    QueueView,
    SessionEventView,
    SessionView,
    SyncView,
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
        error=job.error,
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
        jobs: JobRepository,
        events: EventRepository,
        is_paused: Callable[[], bool],
    ) -> None:
        self._registry = registry
        self._items = items
        self._fields = fields
        self._attributes = attributes
        self._refs = refs
        self._edits = edits
        self._jobs = jobs
        self._events = events
        self._is_paused = is_paused

    # -- reads -------------------------------------------------------------
    def list_workflows(self) -> list[WorkflowView]:
        """Every registered workflow, with its editable-field catalogue."""
        return [workflow_view(workflow) for workflow in self._registry.all()]

    def list_items(
        self,
        workflow_name: str,
        status: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ItemsPageView:
        """The unified view: one row per item, newest-seen first."""
        workflow = self._workflow(workflow_name)
        parsed = self._parse_status(status) if status else None
        items, total = self._items.list(
            workflow.name, parsed, query, limit, offset
        )
        return ItemsPageView(
            workflow=workflow.name,
            count=len(items),
            total=total,
            rows=[self._row_view(workflow, item) for item in items],
        )

    def get_item(self, workflow_name: str, key: str) -> ItemDetailView:
        """One item with read-only attributes, object links and edit history."""
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        return self._detail_view(workflow, item)

    # -- writes ------------------------------------------------------------
    def patch_fields(
        self, workflow_name: str, key: str, changes: Mapping[str, str | None]
    ) -> ItemDetailView:
        """Propose editable values; ``None`` discards a proposal.

        Values are canonicalised with the field's ``ValueType``; an unparseable value is
        rejected with 422 before anything is stored.
        """
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        self._ensure_status(item, _EDITABLE, "editable")

        normalised: dict[str, str | None] = {}
        for field_key, value in changes.items():
            spec = next((f for f in workflow.catalog if f.key == field_key), None)
            if spec is None:
                raise ApiError(422, f"unknown field: {field_key}", "unknown_field")
            if value is None:
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

    def submit(self, workflow_name: str, key: str) -> JobView:
        """Enqueue exactly one ``SUBMIT`` job for an item that has proposed values."""
        workflow = self._workflow(workflow_name)
        item = self._item(workflow, key)
        self._ensure_status(item, _SUBMITTABLE, "submittable")

        if self._is_paused():
            raise ApiError(409, "manual login required", "login_required")

        proposed = {
            field.key
            for field in self._fields.for_item(workflow.name, key).values()
            if field.proposed is not None
        }
        if not proposed:
            raise ApiError(422, "no proposed values to submit", "nothing_to_submit")

        if self._jobs.active_for(workflow.name, key) is not None:
            raise ApiError(409, "an active job already exists for this item", "job_active")

        job = self._jobs.enqueue(workflow.name, JobKind.SUBMIT, key)
        self._items.transition(workflow.name, key, WorkItemStatus.SUBMITTING)
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

    def _row_view(self, workflow: Workflow, item: WorkItem) -> ItemRowView:
        stored = self._fields.for_item(workflow.name, item.key)
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
        active = self._jobs.active_for(workflow.name, item.key)
        return ItemRowView(
            key=item.key,
            status=item.status.value,
            present=item.present,
            epoch=item.epoch,
            record_url=item.record_url,
            approved_at=item.approved_at,
            reason=item.reason,
            fields=fields,
            active_job=job_view(active) if active is not None else None,
        )

    def _detail_view(self, workflow: Workflow, item: WorkItem) -> ItemDetailView:
        row = self._row_view(workflow, item)
        refs = self._refs.for_item(workflow.name, item.key)
        edits = self._edits.for_item(workflow.name, item.key)
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

    def jobs(
        self,
        workflow: str | None,
        kind: str | None,
        status: str | None,
        limit: int,
    ) -> list[JobView]: ...

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
            ok = await run_login(self._settings, self._sessions, reset=False)
            if ok:
                await self._provider.reload(self._runtime.context)
                self._auth.resume()

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
        name = self._workflow_name(workflow)
        watcher = self._watchers.get(name)
        if watcher is None:
            raise ApiError(404, f"no watcher for {name}", "unknown_workflow")

        async def _once() -> None:
            await watcher.refresh_once()

        self._runtime.spawn(_once)

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
        workflow: str | None,
        kind: str | None,
        status: str | None,
        limit: int,
    ) -> list[JobView]:
        return [
            job_view(job)
            for job in self._jobs.query(
                workflow,
                self._kind(kind),
                self._job_status(status),
                limit,
            )
        ]

    def job_logs(self, job_id: int) -> JobLogsView:
        job = self._jobs.get(job_id)
        if job is None:
            raise ApiError(404, f"unknown job {job_id}", "unknown_job")
        return JobLogsView(job=job_view(job), logs=self._jobs.logs(job_id))

    def cancel_job(self, job_id: int) -> None:
        if not self._jobs.cancel(job_id):
            raise ApiError(409, f"job {job_id} is not queued", "job_not_queued")

    def _workflow_name(self, workflow: str) -> str:
        try:
            return self._registry.get(workflow).name
        except Exception as exc:
            raise ApiError(404, f"unknown workflow: {workflow}", "unknown_workflow") from exc

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
