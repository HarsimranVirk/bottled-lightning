"""The workflow seam: what a workflow must provide, and how core calls it.

Two protocols, deliberately narrow, so a future workflow is not forced into the
deviations phase machine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabGroup

from .field import EditableField
from .list_view import ListRow, ListViewSpec
from .models import WorkItem
from .status import ExtractOutcome, SubmitOutcome, WorkItemStatus


class JobLogger(Protocol):
    def __call__(self, message: str) -> None: ...


class ExtractionPipeline(Protocol):
    async def run(
        self, item: WorkItem, tabs: TabGroup, log: JobLogger
    ) -> ExtractOutcome: ...


class SubmissionPipeline(Protocol):
    async def run(
        self, item: WorkItem, tabs: TabGroup, log: JobLogger
    ) -> SubmitOutcome: ...


@dataclass(frozen=True, slots=True)
class Workflow:
    name: str
    route: str
    list_view: ListViewSpec
    catalog: tuple[EditableField, ...]
    adapters: AdapterRegistry
    extraction: ExtractionPipeline
    submission: SubmissionPipeline
    map_row: Callable[[ListRow], Mapping[str, str]]
    terminal_labels: Mapping[WorkItemStatus, str] = field(default_factory=dict)
