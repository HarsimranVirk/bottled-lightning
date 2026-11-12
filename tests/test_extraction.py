"""Extraction pipeline: ordering, persistence, link states, idempotency (fake adapters)."""

from __future__ import annotations

import unittest
from collections.abc import Sequence

from playwright.async_api import Page

from app.core.errors import UnknownRefKind
from app.core.job_logger import JobLogger
from app.core.list_view import ListRow
from app.core.models import WorkItem, utcnow
from app.core.status import ExtractOutcome, RefState, WorkItemStatus
from app.core.workflow import RefKind
from app.salesforce.adapters import (
    AdapterBase,
    AdapterRegistry,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
    absent,
    unresolved,
)
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02 import REF_KINDS
from app.workflows.deviations_z02.catalog import DeviationObject
from app.workflows.deviations_z02.extraction import DeviationsZ02Extraction
from tests.support import DbTestCase

KEY = "Deviation-28102026-484106"
OPP_URL = "https://org/lightning/r/Opportunity/006/view"

#: The four adapters that run in parallel once the opportunity link is known.
PARALLEL_KINDS = (
    DeviationObject.CL_CONTRACT.value,
    DeviationObject.COLLATERAL.value,
    DeviationObject.LMS2_CL_CONTRACT.value,
    DeviationObject.LMS2_COLLATERAL.value,
)


def found(kind: str, name: str = "record") -> DiscoveredRef:
    """A resolvable link for ``kind``, shaped like a real adapter's result."""
    return DiscoveredRef(kind=kind, name=name, url=f"https://org/lightning/r/{name}/view")


class DiscardLog:
    """Job logger that discards every line."""

    def __call__(self, message: str) -> None:
        """Discard one log line."""


class FakeTabs:
    """Tab provider that fails if a pipeline actually opens a page."""

    async def new_page(self, url: str) -> Page:
        """Opening a tab in a fake pipeline is a bug in the test."""
        raise AssertionError("fake adapters must not open tabs")

    async def close_page(self, page: Page) -> None:
        """Closing a tab in a fake pipeline is a bug in the test."""
        raise AssertionError("fake adapters must not close tabs")


class FakeAdapter(AdapterBase):
    """Adapter returning a canned discovery and recording its context."""

    def __init__(self, kind: str, discovery: Discovery) -> None:
        """Store the canned discovery."""
        self.kind = kind
        self.discovery = discovery
        self.calls = 0
        self.contexts: list[DiscoveryContext] = []

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext, log: JobLogger
    ) -> Discovery:
        """Record the context and return the canned discovery."""
        self.calls += 1
        self.contexts.append(context)
        return self.discovery


class FailingAdapter(AdapterBase):
    """Adapter that raises, to test error translation."""

    kind = DeviationObject.OPPORTUNITY.value

    def __init__(self, error: Exception) -> None:
        """Store the error to raise."""
        self._error = error

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext, log: JobLogger
    ) -> Discovery:
        """Raise the configured error."""
        raise self._error


class ExtractionTests(DbTestCase):
    """Extraction pipeline ordering, persistence and incomplete-link handling."""

    def _item(self) -> WorkItem:
        """Create the item the pipeline will extract."""
        items = self.deps().items
        return items.create_present(
            "deviations_z02",
            ListRow(
                key=KEY,
                href=f"/lightning/r/a2f/{KEY}/view",
                columns={},
                approved_at="2026-10-28",
            ),
            utcnow(),
        )

    def _pipeline(
        self,
        adapters: Sequence[AdapterBase],
        *,
        force: bool = False,
        ref_kinds: tuple[RefKind, ...] = REF_KINDS,
    ) -> DeviationsZ02Extraction:
        """Build the pipeline with a fresh adapter registry."""
        deps = self.deps()
        return DeviationsZ02Extraction(
            "deviations_z02",
            deps.items,
            deps.fields,
            deps.attributes,
            deps.refs,
            deps.events,
            AdapterRegistry(adapters),
            ref_kinds=ref_kinds,
            force=force,
        )

    def _ready_adapters(
        self,
        *,
        missing: str | None = None,
        missing_ref: DiscoveredRef | None = None,
    ) -> list[FakeAdapter]:
        """
        The six adapters for an item whose links all resolve.

        ``missing`` replaces that kind's result with ``missing_ref`` (an absent or
        unresolved link) so a test can check how an incomplete item is stored.
        """
        record = FakeAdapter(
            DeviationObject.DEVIATION.value,
            Discovery(
                refs=(
                    DiscoveredRef(
                        kind=DeviationObject.OPPORTUNITY.value,
                        name="Opp",
                        url=OPP_URL,
                    ),
                ),
                attributes={"description": "Loan deviation text"},
                fields={"loan_amount": "25,50,000"},
            ),
        )
        opportunity = FakeAdapter(
            DeviationObject.OPPORTUNITY.value,
            Discovery(attributes={"product_type": "Home Loan"}),
        )
        rest: list[FakeAdapter] = []
        for kind in PARALLEL_KINDS:
            ref = missing_ref if kind == missing else found(kind)
            rest.append(
                FakeAdapter(kind, Discovery(refs=(ref,) if ref is not None else ()))
            )
        return [record, opportunity, *rest]

    def _run(self, pipeline: DeviationsZ02Extraction, item: WorkItem) -> ExtractOutcome:
        """Run the pipeline on a fresh event loop."""
        import asyncio

        return asyncio.run(pipeline.run(item, FakeTabs(), DiscardLog()))

    def test_happy_path_persists_everything(self) -> None:
        """Fields, attributes and all five refs are stored and the item becomes ready."""
        pipeline = self._pipeline(self._ready_adapters())

        outcome = self._run(pipeline, self._item())
        self.assertIs(outcome, ExtractOutcome.EXTRACTED)

        deps = self.deps()
        item = deps.items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.READY)
        self.assertIsNotNone(item.extracted_at)
        self.assertEqual(item.record_url, f"/lightning/r/a2f/{KEY}/view")

        fields = deps.fields.for_item("deviations_z02", KEY)
        self.assertEqual(fields["loan_amount"].extracted, "25,50,000")

        attributes = deps.attributes.for_item("deviations_z02", KEY)
        self.assertEqual(attributes["description"], "Loan deviation text")
        self.assertEqual(attributes["product_type"], "Home Loan")

        refs = deps.refs.for_item("deviations_z02", KEY)
        self.assertEqual(set(refs), {ref.kind for ref in REF_KINDS})
        self.assertTrue(all(ref.state is RefState.FOUND for ref in refs.values()))
        self.assertEqual(refs["opportunity"].url, OPP_URL)
        self.assertIsNone(refs["cl_contract"].reason)

    def test_product_type_is_passed_to_the_cl_contract_adapter(self) -> None:
        """The opportunity's product type reaches the CL-contract adapter (ordering)."""
        adapters = self._ready_adapters()
        contract = adapters[2]
        pipeline = self._pipeline(adapters)

        self._run(pipeline, self._item())

        self.assertEqual(contract.kind, DeviationObject.CL_CONTRACT.value)
        self.assertEqual(len(contract.contexts), 1)
        self.assertEqual(contract.contexts[0].product_type, "Home Loan")
        self.assertEqual(contract.contexts[0].opportunity_url, OPP_URL)

    def test_unparsed_values_are_not_a_skip(self) -> None:
        """Missing values still produce a ready item; parsing is best-effort."""
        record = FakeAdapter(
            DeviationObject.DEVIATION.value,
            Discovery(
                refs=(found(DeviationObject.OPPORTUNITY.value, "Opp"),),
                fields={
                    "property_value": None,
                    "loan_amount": None,
                    "tenure": None,
                    "emi_incl_hffc": None,
                },
            ),
        )
        adapters = self._ready_adapters()
        adapters[0] = record
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, self._item())
        self.assertIs(outcome, ExtractOutcome.EXTRACTED)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.READY)
        fields = self.deps().fields.for_item("deviations_z02", KEY)
        self.assertIsNone(fields["tenure"].extracted)

    def test_unresolved_link_skips_with_the_plain_reason(self) -> None:
        """An ambiguous match is stored as UNRESOLVED and blocks readiness."""
        reason = "There are 2 CL contracts for this product — can't tell which one"
        pipeline = self._pipeline(
            self._ready_adapters(
                missing=DeviationObject.CL_CONTRACT.value,
                missing_ref=unresolved(DeviationObject.CL_CONTRACT.value, reason),
            )
        )

        outcome = self._run(pipeline, self._item())
        self.assertIs(outcome, ExtractOutcome.INCOMPLETE)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertEqual(item.reason, reason)

        refs = self.deps().refs.for_item("deviations_z02", KEY)
        self.assertEqual(len(refs), 5)
        self.assertIs(refs["cl_contract"].state, RefState.UNRESOLVED)
        self.assertEqual(refs["cl_contract"].reason, reason)
        self.assertEqual(refs["cl_contract"].url, "")
        self.assertIs(refs["collateral"].state, RefState.FOUND)

    def test_absent_required_link_skips(self) -> None:
        """A positively empty already-existing object still leaves Z02 incomplete."""
        pipeline = self._pipeline(
            self._ready_adapters(
                missing=DeviationObject.COLLATERAL.value,
                missing_ref=absent(
                    DeviationObject.COLLATERAL.value,
                    "No collateral attached to this opportunity",
                ),
            )
        )

        outcome = self._run(pipeline, self._item())

        self.assertIs(outcome, ExtractOutcome.INCOMPLETE)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)
        refs = self.deps().refs.for_item("deviations_z02", KEY)
        self.assertIs(refs["collateral"].state, RefState.ABSENT)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertEqual(
            item.reason, "No collateral attached to this opportunity"
        )

    def test_absent_optional_link_is_accepted(self) -> None:
        """A workflow may declare a kind optional: ABSENT is then complete."""
        ref_kinds = tuple(
            RefKind(ref.kind, required=ref.kind != DeviationObject.COLLATERAL.value)
            for ref in REF_KINDS
        )
        pipeline = self._pipeline(
            self._ready_adapters(
                missing=DeviationObject.COLLATERAL.value,
                missing_ref=absent(
                    DeviationObject.COLLATERAL.value,
                    "No collateral attached to this opportunity",
                ),
            ),
            ref_kinds=ref_kinds,
        )

        outcome = self._run(pipeline, self._item())

        self.assertIs(outcome, ExtractOutcome.EXTRACTED)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.READY)
        refs = self.deps().refs.for_item("deviations_z02", KEY)
        self.assertIs(refs["collateral"].state, RefState.ABSENT)

    def test_adapter_exception_stores_an_unresolved_link(self) -> None:
        """An adapter crash is logged, and the operator sees a plain reason only."""
        adapters: list[AdapterBase] = list(self._ready_adapters())
        adapters[1] = FailingAdapter(RuntimeError("boom"))
        pipeline = self._pipeline(adapters)

        with self.assertLogs("app.workflows.deviations_z02.extraction", "ERROR"):
            outcome = self._run(pipeline, self._item())

        self.assertIs(outcome, ExtractOutcome.INCOMPLETE)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertEqual(item.reason, "Couldn't open the opportunity page")
        refs = self.deps().refs.for_item("deviations_z02", KEY)
        self.assertIs(refs["opportunity"].state, RefState.UNRESOLVED)
        self.assertEqual(refs["opportunity"].reason, "Couldn't open the opportunity page")

    def test_missing_opportunity_link_skips(self) -> None:
        """Without an opportunity link the item cannot proceed and skips."""
        record = FakeAdapter(DeviationObject.DEVIATION.value, Discovery())
        others = [
            FakeAdapter(kind, Discovery()) for kind in (DeviationObject.OPPORTUNITY.value, *PARALLEL_KINDS)
        ]
        pipeline = self._pipeline([record, *others])

        outcome = self._run(pipeline, self._item())

        self.assertIs(outcome, ExtractOutcome.INCOMPLETE)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertEqual(item.reason, "Couldn't find the opportunity for this deviation")
        self.assertEqual(others[0].calls, 0)

    def test_unreported_kinds_are_stored_as_unresolved(self) -> None:
        """A kind no adapter reported still gets a stored ref with a plain reason."""
        record = FakeAdapter(
            DeviationObject.DEVIATION.value,
            Discovery(refs=(found(DeviationObject.OPPORTUNITY.value, "Opp"),)),
        )
        opportunity = FakeAdapter(
            DeviationObject.OPPORTUNITY.value,
            Discovery(attributes={"product_type": "Home Loan"}),
        )
        others = [FakeAdapter(kind, Discovery()) for kind in PARALLEL_KINDS]
        pipeline = self._pipeline([record, opportunity, *others])

        outcome = self._run(pipeline, self._item())

        self.assertIs(outcome, ExtractOutcome.INCOMPLETE)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)
        refs = self.deps().refs.for_item("deviations_z02", KEY)
        self.assertEqual(len(refs), 5)
        for kind in PARALLEL_KINDS:
            self.assertIs(refs[kind].state, RefState.UNRESOLVED)
            self.assertTrue(refs[kind].reason)
        self.assertIs(refs["opportunity"].state, RefState.FOUND)

    def test_undeclared_ref_kind_fails_loudly(self) -> None:
        """A typo in an adapter's kind raises instead of storing an unread link."""
        adapters: list[AdapterBase] = list(self._ready_adapters())
        adapters[2] = FakeAdapter(
            DeviationObject.CL_CONTRACT.value,
            Discovery(refs=(found("cl_contracts"),)),
        )
        pipeline = self._pipeline(adapters)

        with self.assertLogs("app.workflows.deviations_z02.extraction", "ERROR"):
            outcome = self._run(pipeline, self._item())

        self.assertIs(outcome, ExtractOutcome.FAILED)
        item = self.deps().items.require("deviations_z02", KEY)
        # Left in EXTRACTING on purpose: the reconciler audit turns it into a
        # retryable NEEDS_REVIEW card once the failed job is no longer active.
        self.assertIs(item.status, WorkItemStatus.EXTRACTING)
        self.assertEqual(self.deps().refs.for_item("deviations_z02", KEY), {})
        events = self.deps().events.recent(
            workflow="deviations_z02", item=KEY, limit=5
        )
        self.assertEqual(events[0][0], "extract_failed")
        self.assertIn(UnknownRefKind.__name__, events[0][3] or "")

    def test_declared_kind_without_a_reason_is_refused(self) -> None:
        """Construction fails when a declared kind has no fallback reason."""
        with self.assertRaises(ValueError):
            self._pipeline(
                self._ready_adapters(),
                ref_kinds=(RefKind("not_a_real_kind"),),
            )

    def test_duplicate_kind_is_refused(self) -> None:
        """A kind declared twice would collide on the refs primary key."""
        with self.assertRaises(ValueError):
            self._pipeline(
                self._ready_adapters(),
                ref_kinds=(
                    RefKind(DeviationObject.OPPORTUNITY.value),
                    RefKind(DeviationObject.OPPORTUNITY.value),
                ),
            )

    def test_already_extracted_is_a_no_op(self) -> None:
        """extracted_at short-circuits re-extraction (FR-3.8)."""
        item = self._item()
        deps = self.deps()
        deps.items.transition("deviations_z02", KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(
            "deviations_z02", KEY, WorkItemStatus.READY, extracted_at=utcnow()
        )
        record = FakeAdapter(DeviationObject.DEVIATION.value, Discovery())
        pipeline = self._pipeline([record])

        refreshed = deps.items.require("deviations_z02", KEY)
        outcome = self._run(pipeline, refreshed)

        self.assertIs(outcome, ExtractOutcome.EXTRACTED)
        self.assertEqual(record.calls, 0)
        self.assertEqual(item.key, KEY)

    def test_needs_review_item_retries_without_force(self) -> None:
        """The card's retry is a plain new job: NEEDS_REVIEW -> EXTRACTING is legal."""
        deps = self.deps()
        deps.items.create_present(
            "deviations_z02",
            ListRow(key=KEY, href=f"/lightning/r/a2f/{KEY}/view", columns={}, approved_at=None),
            utcnow(),
        )
        deps.items.transition("deviations_z02", KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(
            "deviations_z02", KEY, WorkItemStatus.NEEDS_REVIEW, reason="old ambiguity"
        )
        record = FakeAdapter(DeviationObject.DEVIATION.value, Discovery())
        pipeline = self._pipeline([record])

        outcome = self._run(pipeline, deps.items.require("deviations_z02", KEY))

        self.assertIs(outcome, ExtractOutcome.INCOMPLETE)
        item = deps.items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertEqual(item.reason, "Couldn't find the opportunity for this deviation")

    def test_successful_retry_clears_the_previous_reason(self) -> None:
        """A retry that resolves every link clears the reason and stores all five."""
        deps = self.deps()
        deps.items.create_present(
            "deviations_z02",
            ListRow(key=KEY, href=f"/lightning/r/a2f/{KEY}/view", columns={}, approved_at=None),
            utcnow(),
        )
        deps.items.transition("deviations_z02", KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(
            "deviations_z02", KEY, WorkItemStatus.NEEDS_REVIEW, reason="old ambiguity"
        )
        pipeline = self._pipeline(self._ready_adapters())

        outcome = self._run(pipeline, deps.items.require("deviations_z02", KEY))
        self.assertIs(outcome, ExtractOutcome.EXTRACTED)
        item = deps.items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.READY)
        self.assertIsNone(item.reason)
        refs = deps.refs.for_item("deviations_z02", KEY)
        self.assertTrue(all(ref.state is RefState.FOUND for ref in refs.values()))

    def test_force_reenters_a_terminal_item_via_present(self) -> None:
        """A legacy skipped item still re-enters through PRESENT when force is set."""
        deps = self.deps()
        deps.items.create_present(
            "deviations_z02",
            ListRow(key=KEY, href=f"/lightning/r/a2f/{KEY}/view", columns={}, approved_at=None),
            utcnow(),
        )
        deps.items.transition("deviations_z02", KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(
            "deviations_z02", KEY, WorkItemStatus.SKIPPED, reason="legacy skip"
        )
        record = FakeAdapter(DeviationObject.DEVIATION.value, Discovery())
        pipeline = self._pipeline([record], force=True)

        outcome = self._run(pipeline, deps.items.require("deviations_z02", KEY))

        self.assertIs(outcome, ExtractOutcome.INCOMPLETE)
        item = deps.items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertEqual(item.reason, "Couldn't find the opportunity for this deviation")

    def test_force_re_extracts(self) -> None:
        """force=True bypasses the one-shot marker."""
        deps = self.deps()
        deps.items.create_present(
            "deviations_z02",
            ListRow(key=KEY, href=f"/lightning/r/a2f/{KEY}/view", columns={}, approved_at=None),
            utcnow(),
        )
        deps.items.transition("deviations_z02", KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(
            "deviations_z02", KEY, WorkItemStatus.READY, extracted_at=utcnow()
        )
        record = FakeAdapter(DeviationObject.DEVIATION.value, Discovery())
        pipeline = self._pipeline([record], force=True)

        outcome = self._run(pipeline, deps.items.require("deviations_z02", KEY))
        self.assertIs(outcome, ExtractOutcome.INCOMPLETE)
        self.assertEqual(record.calls, 1)


if __name__ == "__main__":
    unittest.main()
