"""The workflow seam: what a workflow must provide, and how core calls it.

Two protocols, deliberately narrow, so a future workflow is not forced into the
deviations phase machine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.config import Settings
from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabProvider

from .field import EditableField
from .job_logger import JobLogger
from .list_view import ListRow, ListViewSpec
from .models import PageRef, WorkItem
from .repo.attributes import AttributeRepository
from .repo.events import EventRepository
from .repo.fields import FieldValueRepository
from .repo.refs import PageRefRepository
from .repo.work_items import WorkItemRepository
from .status import ExtractOutcome, RefState, SubmitOutcome, WorkItemStatus

#: Re-exported for the pipelines, which receive this callable seam.
__all__ = ["JobLogger"]


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
class RefKind:
    """
    One SF object link a workflow expects, in display order.

    ``required`` decides whether extraction may call an item ``READY`` without this
    link. Z02 marks all five required: a deviation is not complete without its
    opportunity, CL contract, collateral and both LMS 2.0 links. A workflow can mark a
    kind optional, in which case a positively ``ABSENT`` object is accepted while an
    ``UNRESOLVED`` fetch still needs review.
    """

    kind: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class RefGap:
    """
    The first declared link that keeps an item from being complete.

    ``reason`` is the operator-facing sentence stored on the link itself, or ``None``
    when no ref was stored at all (nothing is known about that object).
    """

    kind: str
    reason: str | None


def incomplete_ref(
    ref_kinds: Sequence[RefKind], refs: Mapping[str, PageRef]
) -> RefGap | None:
    """
    First declared link, in declaration order, that is not usable; ``None`` when complete.

    A required kind must be ``FOUND``. An optional kind may be ``ABSENT`` (the object
    genuinely does not exist) but never ``UNRESOLVED`` (we failed to look), and a kind
    with no stored ref counts as incomplete because we cannot tell whether it was ever
    looked for.

    Called by extraction when deciding ``READY``, and by the reconciler when repairing
    items extracted before link states existed. Sharing it keeps the two from ever
    disagreeing about what "complete" means.

    Example:
        gap = incomplete_ref(workflow.ref_kinds, refs)
        if gap is not None:
            …gap.reason or the workflow's fallback sentence…
    """
    for ref_kind in ref_kinds:
        ref = refs.get(ref_kind.kind)
        if ref is None:
            return RefGap(ref_kind.kind, None)
        if ref.state is RefState.FOUND:
            continue
        if ref.state is RefState.ABSENT and not ref_kind.required:
            continue
        return RefGap(ref.kind, ref.reason)
    return None


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
    ref_kinds: tuple[RefKind, ...] = ()

    def required_ref_kinds(self) -> tuple[str, ...]:
        """Kinds this workflow cannot become ``READY`` without, in display order."""
        return tuple(ref.kind for ref in self.ref_kinds if ref.required)

    def incomplete_ref(self, refs: Mapping[str, PageRef]) -> RefGap | None:
        """First stored link that keeps this item incomplete, if any."""
        return incomplete_ref(self.ref_kinds, refs)


#: Builds one fully wired workflow from global settings and its repositories.
#:
#: Builders are plain module-level functions, not classes. ``app/main.py`` holds them
#: in a literal ``BUILDERS`` tuple and calls each once at boot; adding a workflow is
#: one import plus one tuple entry. Each builder owns its workflow's
#: ``AdapterRegistry`` (adapters are per-workflow) and must not open a browser or
#: touch the database during construction — that happens when jobs run.
WorkflowBuilder = Callable[[Settings, WorkflowDeps], Workflow]
