"""The workflow seam: what a workflow must provide, and how core calls it.

Two protocols, deliberately narrow, so a future workflow is not forced into the
deviations phase machine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabProvider

from .field import EditableField
from .list_view import ListRow, ListViewSpec
from .models import WorkItem
from .repo.attributes import AttributeRepository
from .repo.events import EventRepository
from .repo.fields import FieldValueRepository
from .repo.refs import PageRefRepository
from .repo.work_items import WorkItemRepository
from .status import ExtractOutcome, SubmitOutcome, WorkItemStatus


class JobLogger(Protocol):
    """Callable that records one job progress line."""

    def __call__(self, message: str) -> None:
        """Append one line to the job log."""
        ...


class ExtractionPipeline(Protocol):
    """
    What a workflow must implement to extract data (FR-3).

    The pipeline receives one item and a tab group, does all browser work, persists
    what it found through repositories, and returns an outcome. It must not decide
    retries or job status — the worker does that.

    Example (test double):
        class FakeExtraction:
            async def run(self, item, tabs, log) -> ExtractOutcome:
                log(f"extracting {item.key}")
                return ExtractOutcome.EXTRACTED
    """

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> ExtractOutcome:
        """Discover and persist one item's data."""
        ...


class SubmissionPipeline(Protocol):
    """
    What a workflow must implement to submit changes (FR-6).

    The pipeline applies values, verifies them, performs the final action and
    returns an outcome. It owns the phase markers on the job and must never reach
    the final action after a failed validation (invariant I3).

    Returns ``COMPLETED``, ``ALREADY_CLOSED`` or ``FAILED``; the worker maps those
    to job status.
    """

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """Apply, validate and complete one item."""
        ...


@dataclass(frozen=True, slots=True)
class WorkflowDeps:
    """
    The repositories a workflow implementation is allowed to use.

    Passing them as one object keeps ``build_workflow`` signatures stable and makes
    it obvious that pipelines never reach into the database directly.
    """

    items: WorkItemRepository
    fields: FieldValueRepository
    attributes: AttributeRepository
    refs: PageRefRepository
    events: EventRepository


@dataclass(frozen=True, slots=True)
class Workflow:
    """
    One registered workflow: list view, catalogue, adapters and pipelines.

    ``name`` scopes every database row; ``route`` is the REST noun (Z02 registers as
    ``deviations_z02`` but mounts at ``/api/deviations``). ``map_row`` is the only
    hook the generic reconciler needs to understand a workflow's list columns.
    """

    name: str
    route: str
    list_view: ListViewSpec
    catalog: tuple[EditableField, ...]
    adapters: AdapterRegistry
    extraction: ExtractionPipeline
    submission: SubmissionPipeline
    map_row: Callable[[ListRow], Mapping[str, str]]
    terminal_labels: Mapping[WorkItemStatus, str] = field(default_factory=dict)
    ref_kinds: tuple[str, ...] = ()
