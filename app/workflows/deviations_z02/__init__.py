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
from app.core.workflow import RefKind, Workflow, WorkflowDeps
from app.salesforce.urls import list_view_url

from .adapters import build_adapters
from .catalog import FIELD_CATALOG, DeviationObject
from .extraction import DeviationsZ02Extraction
from .submission import DeviationsZ02Submission

WORKFLOW_NAME = "deviations_z02"
LIST_OBJECT_API = "Consumer_Loan_Deviation__c"
LIST_FILTER = "Z2_Loan_para_pricing1"
#: Safe pattern: the middle segment is 8 digits, so ``\d{2,4}`` never matches.
LIST_PATTERN = r"Deviation-\d+-\d+"

#: Every SF object link this workflow expects, in display order.
#:
#: Single source of truth for three consumers: the workflow's declaration (readiness
#: and submission), extraction (one stored ref per kind) and the API projection. All
#: five are required — a deviation is incomplete without any of them. Adding a kind
#: here also needs an adapter and a plain fallback reason in ``extraction``.
REF_KINDS: tuple[RefKind, ...] = (
    RefKind(DeviationObject.OPPORTUNITY.value),
    RefKind(DeviationObject.CL_CONTRACT.value),
    RefKind(DeviationObject.COLLATERAL.value),
    RefKind(DeviationObject.LMS2_CL_CONTRACT.value),
    RefKind(DeviationObject.LMS2_COLLATERAL.value),
)


def map_row(row: ListRow) -> Mapping[str, str]:
    """List columns → stored attributes. The Z02 list only exposes the key and the
    approval date, both stored as columns, so there is nothing extra to map yet."""
    return {}


def build_workflow(
    settings: Settings,
    deps: WorkflowDeps,
    *,
    force: bool = False,
) -> Workflow:
    """
    Build the Z02 workflow and its per-workflow adapter registry.

    Called once at boot by ``Stack`` through the ``BUILDERS`` tuple, and by the dev
    smoke tools. Adapters are constructed here (never shared between workflows):
    each registry carries the concrete Salesforce object implementations for this
    workflow only.

    ``force`` re-extracts items that were already visited; the smoke tools use it,
    the app leaves it ``False``. Raises only if an adapter implementation is missing
    at import time; construction itself does no browser work.
    """
    adapters = build_adapters(settings.org_base, settings.timeouts)
    extraction = DeviationsZ02Extraction(
        WORKFLOW_NAME,
        deps.items,
        deps.fields,
        deps.attributes,
        deps.refs,
        deps.events,
        adapters,
        ref_kinds=REF_KINDS,
        timeouts=settings.timeouts,
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
        ref_kinds=REF_KINDS,
        timeouts=settings.timeouts,
    )
    return Workflow(
        name=WORKFLOW_NAME,
        route="deviations",
        list_view=ListViewSpec(
            url=list_view_url(settings.org_base, LIST_OBJECT_API, LIST_FILTER),
            pattern=LIST_PATTERN,
        ),
        catalog=FIELD_CATALOG,
        adapters=adapters,
        extraction=extraction,
        submission=submission,
        map_row=map_row,
        terminal_labels={WorkItemStatus.COMPLETED: "Implemented"},
        ref_kinds=REF_KINDS,
    )
