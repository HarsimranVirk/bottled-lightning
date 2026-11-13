"""Z02 extraction: one deviation → editable values, attributes and page refs.

Ordering is the only part that matters: the record page is the source of the Opportunity
link, and the Opportunity page is the source of the product type the CL-contract match
needs. Everything after that runs in parallel tabs (FR-3.6).

Every expected link ends up stored exactly once, as ``FOUND``, ``ABSENT`` or
``UNRESOLVED``. The pipeline never guesses: a link it could not resolve keeps a plain
reason for the operator, and the first such ref (in declaration order) is what makes the
item incomplete.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import replace

from app.config import TimeoutPolicy
from app.core.errors import SessionExpired, UnknownRefKind
from app.core.models import PageRef, WorkItem, utcnow
from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import (
    TERMINAL_STATUSES,
    ExtractOutcome,
    RefState,
    WorkItemStatus,
)
from app.core.workflow import JobLogger, RefKind, incomplete_ref
from app.salesforce.adapters import (
    AdapterRegistry,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
    ObjectAdapter,
    unresolved,
)
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02.catalog import DeviationObject

logger = logging.getLogger(__name__)

_PARALLEL_KINDS: tuple[str, ...] = (
    DeviationObject.CL_CONTRACT.value,
    DeviationObject.COLLATERAL.value,
    DeviationObject.LMS2_CL_CONTRACT.value,
    DeviationObject.LMS2_COLLATERAL.value,
)

#: Plain-language reason for a declared link that no adapter reported at all.
#:
#: Adapters normally return one ref per kind, with a better reason of their own. This
#: table is the safety net that keeps the "one stored ref per kind" invariant when an
#: adapter bails out early; the text must stay operator-readable (no exception detail).
_KIND_REASONS: dict[str, str] = {
    DeviationObject.OPPORTUNITY.value: (
        "Couldn't find the opportunity for this deviation"
    ),
    DeviationObject.CL_CONTRACT.value: "Couldn't find the CL contract for this product",
    DeviationObject.COLLATERAL.value: (
        "Couldn't find the collateral for this opportunity"
    ),
    DeviationObject.LMS2_CL_CONTRACT.value: (
        "Couldn't find the LMS 2.0 CL contract for this product"
    ),
    DeviationObject.LMS2_COLLATERAL.value: (
        "Couldn't find the LMS 2.0 collateral for this opportunity"
    ),
}

#: Plain-language reason when an adapter raised while trying to resolve its link.
#:
#: The exception type and message go to the job log only; the operator sees that the
#: page did not open, which is the only part they can act on.
_OPEN_FAILED: dict[str, str] = {
    DeviationObject.OPPORTUNITY.value: "Couldn't open the opportunity page",
    DeviationObject.CL_CONTRACT.value: "Couldn't open the CL contract list",
    DeviationObject.COLLATERAL.value: "Couldn't open the collateral list",
    DeviationObject.LMS2_CL_CONTRACT.value: "Couldn't open the LMS 2.0 CL contract list",
    DeviationObject.LMS2_COLLATERAL.value: "Couldn't open the LMS 2.0 collateral list",
}


class DeviationsZ02Extraction:
    """
    Extraction pipeline for Z02 (class design, section 9.2).

    Order is a dependency chain: the record page yields the opportunity link, the
    opportunity yields the product type the CL-contract match needs, and only then
    can the remaining four objects be discovered in parallel.

    Outcomes: ``EXTRACTED`` (values stored, item READY), ``INCOMPLETE`` (a required link
    is absent or unresolved: item NEEDS_REVIEW with that plain reason, job failed, no
    automatic retry), ``FAILED`` (persistence or programming problem; the item is
    returned to PRESENT so it can be retried).

    ``ref_kinds`` is the workflow's declaration (see ``REF_KINDS``) and is validated at
    construction: every declared kind needs a plain fallback reason, and any adapter
    that reports a kind outside it raises :class:`UnknownRefKind` before anything is
    stored.
    """

    def __init__(
        self,
        workflow: str,
        items: WorkItemRepository,
        fields: FieldValueRepository,
        attributes: AttributeRepository,
        refs: PageRefRepository,
        events: EventRepository,
        adapters: AdapterRegistry,
        *,
        ref_kinds: tuple[RefKind, ...],
        timeouts: TimeoutPolicy,
        force: bool = False,
    ) -> None:
        """
        Wire repositories, adapters, the declared link kinds and the timeout policy;
        ``force`` re-extracts.

        ``timeouts`` is read once per run, so a profile change applies to the next job.

        Raises:
            ValueError: the workflow declares no link kinds, declares one twice, or
                declares a kind without an entry in ``_KIND_REASONS``/``_OPEN_FAILED``.
        """
        self._workflow = workflow
        self._items = items
        self._fields = fields
        self._attributes = attributes
        self._refs = refs
        self._events = events
        self._adapters = adapters
        self._timeouts = timeouts
        self._force = force
        self._declared = ref_kinds
        self._ref_kinds = tuple(ref.kind for ref in ref_kinds)
        self._expected = frozenset(self._ref_kinds)
        if not self._ref_kinds:
            raise ValueError(f"{workflow}: no link kinds declared")
        if len(self._ref_kinds) != len(self._expected):
            raise ValueError(f"{workflow}: duplicate link kinds in {self._ref_kinds!r}")
        missing = [
            kind
            for kind in self._ref_kinds
            if kind not in _KIND_REASONS or kind not in _OPEN_FAILED
        ]
        if missing:
            raise ValueError(
                f"{workflow}: link kinds without a plain reason: {missing!r}"
            )

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> ExtractOutcome:
        """
        Extract one deviation and persist everything it found.

        The browser work runs under one whole-run budget (the same network profile as
        submissions). An overrun is ``INCOMPLETE``: the item is parked for the operator
        with a plain reason and is never auto-retried, so a stuck page costs one budget
        rather than two.

        Example log for one item:
            extract start: deviations_z02/Deviation-03112026-486382
            Deviation-03112026-486382: extracted
            done: extracted
        """
        if item.extracted_at is not None and not self._force:
            log(f"{item.key}: already extracted; nothing to do")
            return ExtractOutcome.EXTRACTED
        if not item.record_url:
            # A row whose list view exposes no record link is not operator work: there
            # is nothing to open and no reason to show a card. It stays present, and the
            # reconciler queues extraction once a refresh supplies the link.
            log(f"{item.key}: no record link on the list row; leaving it present")
            return ExtractOutcome.EXTRACTED

        if self._force and item.status in TERMINAL_STATUSES:
            # A forced retry is a new attempt: terminal states re-enter via PRESENT
            # (the state machine never jumps terminal -> EXTRACTING).
            item = self._items.transition(
                self._workflow, item.key, WorkItemStatus.PRESENT, clear_reason=True
            )
        self._items.transition(self._workflow, item.key, WorkItemStatus.EXTRACTING)
        timeouts = self._timeouts.current()
        log(
            "budget: "
            f"profile={timeouts.profile.value} "
            f"action={timeouts.action_ms // 1000}s "
            f"total={timeouts.submission_ms // 1000}s"
        )
        try:
            async with asyncio.timeout(timeouts.submission_ms / 1000):
                discoveries = await self._discover_all(item, tabs, log)
                refs = self._collect(item, discoveries)
                self._persist(item, discoveries, refs)
            gap = incomplete_ref(self._declared, {ref.kind: ref for ref in refs})
            if gap is not None:
                reason = gap.reason or _KIND_REASONS[gap.kind]
                return self._incomplete(item, reason, log)
            self._items.transition(
                self._workflow,
                item.key,
                WorkItemStatus.READY,
                extracted_at=utcnow(),
                clear_reason=True,
            )
            self._events.emit(
                "extracted", workflow=self._workflow, item=item.key
            )
            log(f"{item.key}: extracted")
            return ExtractOutcome.EXTRACTED
        except SessionExpired:
            raise
        except TimeoutError:
            return self._incomplete(
                item,
                f"extraction did not finish within "
                f"{timeouts.submission_ms // 1000}s",
                log,
            )
        except Exception as exc:
            logger.exception("extraction failed for %s", item.key)
            # The item is left in EXTRACTING on purpose: the reconciler's audit turns it
            # into a retryable NEEDS_REVIEW card once no job is running for it. Returning
            # it to PRESENT here would make it invisible and progressless.
            self._events.emit(
                "extract_failed",
                workflow=self._workflow,
                item=item.key,
                detail=f"{type(exc).__name__}: {exc}",
            )
            log(f"{item.key}: extraction failed: {type(exc).__name__}: {exc}")
            return ExtractOutcome.FAILED

    # -- steps -------------------------------------------------------------
    async def _discover_all(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> list[Discovery]:
        """Run the record, opportunity and parallel object discoveries."""
        context = DiscoveryContext(item_key=item.key, record_url=item.record_url or "")

        record = await self._discover(
            DeviationObject.DEVIATION.value, tabs, context, log
        )
        discoveries = [record]
        opportunity = _ref(record, DeviationObject.OPPORTUNITY.value)
        if opportunity is None or opportunity.state is not RefState.FOUND:
            # Without a usable link there is nothing else to open; the remaining kinds
            # are collected as unresolved with their fallback reasons.
            log(f"{item.key}: no opportunity link to follow")
            return discoveries

        context = replace(context, opportunity_url=opportunity.url)
        opportunity_discovery = await self._discover(
            DeviationObject.OPPORTUNITY.value, tabs, context, log
        )
        discoveries.append(opportunity_discovery)
        context = replace(
            context, product_type=opportunity_discovery.attributes.get("product_type")
        )

        parallel = await asyncio.gather(
            *(self._discover(kind, tabs, context, log) for kind in _PARALLEL_KINDS)
        )
        discoveries.extend(parallel)
        return discoveries

    async def _discover(
        self,
        kind: str,
        tabs: TabProvider,
        context: DiscoveryContext,
        log: JobLogger,
    ) -> Discovery:
        """Run one adapter, turning an unexpected error into an unresolved link."""
        adapter: ObjectAdapter = self._adapters.get(kind)
        started = time.monotonic()
        log(f"discover: {kind}: start")
        try:
            discovery = await adapter.discover(tabs, context, log)
        except SessionExpired:
            raise
        except Exception as exc:
            logger.exception("adapter %s failed for %s", kind, context.item_key)
            log(f"{context.item_key}: {kind} failed: {type(exc).__name__}: {exc}")
            if kind not in self._expected:
                return Discovery()
            return Discovery(refs=(unresolved(kind, _OPEN_FAILED[kind]),))
        elapsed = time.monotonic() - started
        summary = _discovery_summary(discovery)
        log(f"discover: {kind}: done in {elapsed:.1f}s — {summary}")
        return discovery

    def _collect(
        self, item: WorkItem, discoveries: Sequence[Discovery]
    ) -> list[PageRef]:
        """
        Merge adapter slices into exactly one stored ref per declared kind.

        Later discoveries win, because the opportunity adapter confirms the link the
        record adapter found: a link whose page never opened must be stored as
        unresolved, not as a URL submission could try to use. Kinds no adapter reported
        get the plain fallback reason, so a stored item always explains every link.

        Raises:
            UnknownRefKind: an adapter reported a kind the workflow never declared.
        """
        by_kind: dict[str, DiscoveredRef] = {}
        for discovery in discoveries:
            for ref in discovery.refs:
                if ref.kind not in self._expected:
                    raise UnknownRefKind(
                        f"{self._workflow}: {ref.kind!r} is not a declared link kind"
                    )
                by_kind[ref.kind] = ref
        refs: list[PageRef] = []
        for kind in self._ref_kinds:
            found = by_kind.get(kind) or unresolved(kind, _KIND_REASONS[kind])
            refs.append(
                PageRef(
                    workflow=self._workflow,
                    item=item.key,
                    kind=kind,
                    name=found.name,
                    url=found.url,
                    state=found.state,
                    reason=found.reason,
                )
            )
        return refs

    def _persist(
        self, item: WorkItem, discoveries: Sequence[Discovery], refs: Sequence[PageRef]
    ) -> None:
        """Write merged discoveries: fields, attributes and refs."""
        fields: dict[str, str | None] = {}
        attributes: dict[str, str | None] = {}
        for discovery in discoveries:
            fields.update(discovery.fields)
            attributes.update(discovery.attributes)
        if fields:
            self._fields.set_extracted(self._workflow, item.key, fields)
        if attributes:
            self._attributes.upsert(self._workflow, item.key, attributes)
        self._refs.replace(self._workflow, item.key, refs)

    def _incomplete(self, item: WorkItem, reason: str, log: JobLogger) -> ExtractOutcome:
        """
        Leave the item for the operator: ``NEEDS_REVIEW`` plus the plain reason.

        Called when a required link is absent or unresolved. Nothing is retried
        automatically — the card's Retry action is the only way back to ``EXTRACTING``.
        """
        self._items.transition(
            self._workflow, item.key, WorkItemStatus.NEEDS_REVIEW, reason=reason
        )
        self._events.emit(
            "needs_review", workflow=self._workflow, item=item.key, detail=reason
        )
        log(f"{item.key}: needs review — {reason}")
        return ExtractOutcome.INCOMPLETE


def _ref(discovery: Discovery, kind: str) -> DiscoveredRef | None:
    """Pick a ref of one kind out of a discovery."""
    return next((ref for ref in discovery.refs if ref.kind == kind), None)


def _discovery_summary(discovery: Discovery) -> str:
    """One-line log summary of what an adapter contributed."""
    refs = ", ".join(f"{ref.kind}:{ref.state.value}" for ref in discovery.refs)
    return (
        f"refs=[{refs}], "
        f"fields={len(discovery.fields)}, "
        f"attributes={len(discovery.attributes)}"
    )
