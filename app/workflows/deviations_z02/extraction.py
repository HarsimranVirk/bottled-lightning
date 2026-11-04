"""Z02 extraction: one deviation → editable values, attributes and page refs.

Ordering is the only part that matters: the record page is the source of the Opportunity
link, and the Opportunity page is the source of the product type the CL-contract match
needs. Everything after that runs in parallel tabs (FR-3.6).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import replace

from app.core.errors import SessionExpired
from app.core.models import PageRef, WorkItem, utcnow
from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import ExtractOutcome, WorkItemStatus
from app.core.workflow import JobLogger
from app.salesforce.adapters import (
    AdapterRegistry,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
    ObjectAdapter,
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


class DeviationsZ02Extraction:
    """
    Extraction pipeline for Z02 (class design, section 9.2).

    Order is a dependency chain: the record page yields the opportunity link, the
    opportunity yields the product type the CL-contract match needs, and only then
    can the remaining four objects be discovered in parallel.

    Outcomes: ``EXTRACTED`` (values stored, item READY), ``SKIPPED`` (ambiguity or
    missing opportunity link, item SKIPPED with a reason), ``FAILED`` (persistence
    problem; the item is returned to PRESENT so it can be retried).
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
        force: bool = False,
    ) -> None:
        """Wire repositories and adapters; ``force`` re-extracts."""
        self._workflow = workflow
        self._items = items
        self._fields = fields
        self._attributes = attributes
        self._refs = refs
        self._events = events
        self._adapters = adapters
        self._force = force

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> ExtractOutcome:
        """
        Extract one deviation and persist everything it found.

        Example log for one item:
            extract start: deviations_z02/Deviation-03112026-486382
            Deviation-03112026-486382: extracted
            done: extracted
        """
        if item.extracted_at is not None and not self._force:
            log(f"{item.key}: already extracted; nothing to do")
            return ExtractOutcome.EXTRACTED
        if not item.record_url:
            return self._skip(item, "no record URL on the list row", log)

        self._items.transition(self._workflow, item.key, WorkItemStatus.EXTRACTING)
        try:
            discoveries = await self._discover_all(item, tabs, log)
            self._persist(item, discoveries)
            skip_reason = _first_skip(discoveries)
            if skip_reason is not None:
                return self._skip(item, skip_reason, log)
            self._items.transition(
                self._workflow,
                item.key,
                WorkItemStatus.READY,
                extracted_at=utcnow(),
            )
            self._events.emit(
                "extracted", workflow=self._workflow, item=item.key
            )
            log(f"{item.key}: extracted")
            return ExtractOutcome.EXTRACTED
        except SessionExpired:
            raise
        except Exception as exc:
            logger.exception("extraction failed for %s", item.key)
            with suppress(Exception):
                self._items.transition(
                    self._workflow, item.key, WorkItemStatus.PRESENT
                )
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
        if record.skip_reason is not None:
            return discoveries

        opportunity = _ref(record, DeviationObject.OPPORTUNITY.value)
        context = replace(
            context, opportunity_url=opportunity.url if opportunity else None
        )
        if opportunity is None:
            discoveries.append(
                Discovery(skip_reason=f"no Opportunity link for {item.key}")
            )
            return discoveries

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
        """Run one adapter, turning unexpected errors into a skip."""
        adapter: ObjectAdapter = self._adapters.get(kind)
        try:
            return await adapter.discover(tabs, context)
        except SessionExpired:
            raise
        except Exception as exc:
            logger.exception("adapter %s failed for %s", kind, context.item_key)
            log(f"{context.item_key}: {kind} failed: {type(exc).__name__}: {exc}")
            return Discovery(skip_reason=f"internal error in {kind}: {exc}")

    def _persist(self, item: WorkItem, discoveries: list[Discovery]) -> None:
        """Write merged discoveries: fields, attributes and refs."""
        fields: dict[str, str | None] = {}
        attributes: dict[str, str | None] = {}
        refs: dict[str, DiscoveredRef] = {}
        for discovery in discoveries:
            fields.update(discovery.fields)
            attributes.update(discovery.attributes)
            for ref in discovery.refs:
                refs[ref.kind] = ref
        if fields:
            self._fields.set_extracted(self._workflow, item.key, fields)
        if attributes:
            self._attributes.upsert(self._workflow, item.key, attributes)
        self._refs.replace(
            self._workflow,
            item.key,
            [
                PageRef(
                    workflow=self._workflow,
                    item=item.key,
                    kind=ref.kind,
                    name=ref.name,
                    url=ref.url,
                )
                for ref in refs.values()
            ],
        )

    def _skip(self, item: WorkItem, reason: str, log: JobLogger) -> ExtractOutcome:
        """Move the item to SKIPPED and record why."""
        self._items.transition(
            self._workflow, item.key, WorkItemStatus.SKIPPED, reason=reason
        )
        self._events.emit(
            "skipped", workflow=self._workflow, item=item.key, detail=reason
        )
        log(f"{item.key}: skipped — {reason}")
        return ExtractOutcome.SKIPPED


def _ref(discovery: Discovery, kind: str) -> DiscoveredRef | None:
    """Pick a ref of one kind out of a discovery."""
    return next((ref for ref in discovery.refs if ref.kind == kind), None)


def _first_skip(discoveries: list[Discovery]) -> str | None:
    """First skip reason across discoveries, if any."""
    for discovery in discoveries:
        if discovery.skip_reason is not None:
            return discovery.skip_reason
    return None
