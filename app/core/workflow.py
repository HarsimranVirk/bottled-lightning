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
    """What a workflow must implement to extract data (FR-3)."""

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> ExtractOutcome:
        """Discover and persist one item's data."""
        ...


class SubmissionPipeline(Protocol):
    """What a workflow must implement to submit changes (FR-6)."""

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """Apply, validate and complete one item."""
        ...


@dataclass(frozen=True, slots=True)
class WorkflowDeps:
    """Repositories a workflow implementation is allowed to use."""

    items: WorkItemRepository
    fields: FieldValueRepository
    attributes: AttributeRepository
    refs: PageRefRepository
    events: EventRepository


@dataclass(frozen=True, slots=True)
class Workflow:
    """One registered workflow: list view, catalogue, adapters and pipelines."""

    name: str
    route: str
    list_view: ListViewSpec
    catalog: tuple[EditableField, ...]
    adapters: AdapterRegistry
    extraction: ExtractionPipeline
    submission: SubmissionPipeline
    map_row: Callable[[ListRow], Mapping[str, str]]
    terminal_labels: Mapping[WorkItemStatus, str] = field(default_factory=dict)
