"""The Z02 loan-deviation workflow: registration seam.

``build_workflow`` is the single wiring point. Pipelines are placeholders until Phases 3
and 6 of the refactor plan; the catalog, list view and labels are already final.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.config import Settings
from app.core.list_view import ListRow, ListViewSpec
from app.core.models import WorkItem
from app.core.status import ExtractOutcome, SubmitOutcome, WorkItemStatus
from app.core.workflow import JobLogger, Workflow
from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabGroup

from .catalog import FIELD_CATALOG

WORKFLOW_NAME = "deviations_z02"


class _PendingExtraction:
    async def run(
        self, item: WorkItem, tabs: TabGroup, log: JobLogger
    ) -> ExtractOutcome:
        raise NotImplementedError("DeviationsZ02Extraction lands in refactor Phase 3")


class _PendingSubmission:
    async def run(
        self, item: WorkItem, tabs: TabGroup, log: JobLogger
    ) -> SubmitOutcome:
        raise NotImplementedError("DeviationsZ02Submission lands in refactor Phase 6")


def map_row(row: ListRow) -> Mapping[str, str]:
    """List columns → stored attributes. The Z02 list only exposes the key and the
    approval date, both stored as columns, so there is nothing extra to map yet."""
    return {}


def build_workflow(settings: Settings, adapters: AdapterRegistry) -> Workflow:
    return Workflow(
        name=WORKFLOW_NAME,
        route="deviations",
        list_view=ListViewSpec(
            url=settings.deviations_z02_list_url,
            pattern=settings.deviations_z02_pattern,
        ),
        catalog=FIELD_CATALOG,
        adapters=adapters,
        extraction=_PendingExtraction(),
        submission=_PendingSubmission(),
        map_row=map_row,
        terminal_labels={WorkItemStatus.COMPLETED: "Implemented"},
    )
