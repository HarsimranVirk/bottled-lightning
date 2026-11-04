"""The Z02 loan-deviation workflow: registration seam.

``build_workflow`` is the single wiring point. Extraction is implemented; submission is a
placeholder until refactor Phase 6.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.config import Settings
from app.core.list_view import ListRow, ListViewSpec
from app.core.models import WorkItem
from app.core.status import SubmitOutcome, WorkItemStatus
from app.core.workflow import JobLogger, Workflow, WorkflowDeps
from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabProvider

from .catalog import FIELD_CATALOG
from .extraction import DeviationsZ02Extraction

WORKFLOW_NAME = "deviations_z02"


class _PendingSubmission:
    """Placeholder until the submission pipeline lands (Phase 6)."""

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """Always raises: submission is not implemented yet."""
        raise NotImplementedError("DeviationsZ02Submission lands in refactor Phase 6")


def map_row(row: ListRow) -> Mapping[str, str]:
    """List columns → stored attributes. The Z02 list only exposes the key and the
    approval date, both stored as columns, so there is nothing extra to map yet."""
    return {}


def build_workflow(
    settings: Settings,
    deps: WorkflowDeps,
    adapters: AdapterRegistry,
    *,
    force: bool = False,
) -> Workflow:
    """Build the Z02 workflow from settings, repositories and adapters."""
    extraction = DeviationsZ02Extraction(
        WORKFLOW_NAME,
        deps.items,
        deps.fields,
        deps.attributes,
        deps.refs,
        deps.events,
        adapters,
        force=force,
    )
    return Workflow(
        name=WORKFLOW_NAME,
        route="deviations",
        list_view=ListViewSpec(
            url=settings.deviations_z02_list_url,
            pattern=settings.deviations_z02_pattern,
        ),
        catalog=FIELD_CATALOG,
        adapters=adapters,
        extraction=extraction,
        submission=_PendingSubmission(),
        map_row=map_row,
        terminal_labels={WorkItemStatus.COMPLETED: "Implemented"},
    )
