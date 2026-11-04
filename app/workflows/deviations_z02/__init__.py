"""The Z02 loan-deviation workflow: registration seam.

``build_workflow`` is the single wiring point. Extraction and the apply/validate half of
submission are implemented; the final Implement action is deliberately disabled during
Phase 6 bring-up (``final_action=False``).
"""

from __future__ import annotations

from collections.abc import Mapping

from app.config import Settings
from app.core.list_view import ListRow, ListViewSpec
from app.core.status import WorkItemStatus
from app.core.workflow import Workflow, WorkflowDeps
from app.salesforce.adapters import AdapterRegistry

from .catalog import FIELD_CATALOG
from .extraction import DeviationsZ02Extraction
from .submission import DeviationsZ02Submission

WORKFLOW_NAME = "deviations_z02"


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
    submission = DeviationsZ02Submission(
        WORKFLOW_NAME,
        deps.items,
        deps.fields,
        deps.refs,
        deps.events,
        adapters,
        FIELD_CATALOG,
        final_action=False,
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
        submission=submission,
        map_row=map_row,
        terminal_labels={WorkItemStatus.COMPLETED: "Implemented"},
        ref_kinds=(
            "opportunity",
            "cl_contract",
            "collateral",
            "lms2_cl_contract",
            "lms2_collateral",
        ),
    )
