"""Extraction pipeline: ordering, persistence, skips, idempotency (fake adapters)."""

from __future__ import annotations

import unittest

from playwright.async_api import Page

from app.core.list_view import ListRow
from app.core.models import WorkItem, utcnow
from app.core.status import ExtractOutcome, WorkItemStatus
from app.salesforce.adapters import (
    AdapterBase,
    AdapterRegistry,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
)
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02.catalog import DeviationObject
from app.workflows.deviations_z02.extraction import DeviationsZ02Extraction
from tests.support import DbTestCase

KEY = "Deviation-28102026-484106"
OPP_URL = "https://org/lightning/r/Opportunity/006/view"


class FakeTabs:
    async def new_page(self, url: str) -> Page:
        raise AssertionError("fake adapters must not open tabs")

    async def close_page(self, page: Page) -> None:
        raise AssertionError("fake adapters must not close tabs")


class FakeAdapter(AdapterBase):
    def __init__(self, kind: str, discovery: Discovery) -> None:
        self.kind = kind
        self.discovery = discovery
        self.calls = 0
        self.contexts: list[DiscoveryContext] = []

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext
    ) -> Discovery:
        self.calls += 1
        self.contexts.append(context)
        return self.discovery


class FailingAdapter(AdapterBase):
    kind = DeviationObject.OPPORTUNITY.value

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext
    ) -> Discovery:
        raise self._error


class ExtractionTests(DbTestCase):
    def _item(self) -> WorkItem:
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
        self, adapters: list[AdapterBase], *, force: bool = False
    ) -> DeviationsZ02Extraction:
        deps = self.deps()
        return DeviationsZ02Extraction(
            "deviations_z02",
            deps.items,
            deps.fields,
            deps.attributes,
            deps.refs,
            deps.events,
            AdapterRegistry(adapters),
            force=force,
        )

    def _run(self, pipeline: DeviationsZ02Extraction, item: WorkItem) -> ExtractOutcome:
        import asyncio

        return asyncio.run(pipeline.run(item, FakeTabs(), lambda _m: None))

    def test_happy_path_persists_everything(self) -> None:
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
        contract = FakeAdapter(
            DeviationObject.CL_CONTRACT.value,
            Discovery(
                refs=(
                    DiscoveredRef(
                        kind=DeviationObject.CL_CONTRACT.value,
                        name="LAI-1",
                        url="https://org/lightning/r/LAI/1/view",
                    ),
                )
            ),
        )
        others = [
            FakeAdapter(kind, Discovery())
            for kind in (
                DeviationObject.COLLATERAL.value,
                DeviationObject.LMS2_CL_CONTRACT.value,
                DeviationObject.LMS2_COLLATERAL.value,
            )
        ]
        pipeline = self._pipeline([record, opportunity, contract, *others])

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
        self.assertEqual(set(refs), {"opportunity", "cl_contract"})
        self.assertEqual(refs["cl_contract"].name, "LAI-1")

    def test_product_type_is_passed_to_the_cl_contract_adapter(self) -> None:
        record = FakeAdapter(
            DeviationObject.DEVIATION.value,
            Discovery(
                refs=(
                    DiscoveredRef(
                        kind=DeviationObject.OPPORTUNITY.value,
                        name="Opp",
                        url=OPP_URL,
                    ),
                )
            ),
        )
        opportunity = FakeAdapter(
            DeviationObject.OPPORTUNITY.value,
            Discovery(attributes={"product_type": "Home Loan"}),
        )
        contract = FakeAdapter(DeviationObject.CL_CONTRACT.value, Discovery())
        others = [
            FakeAdapter(kind, Discovery())
            for kind in (
                DeviationObject.COLLATERAL.value,
                DeviationObject.LMS2_CL_CONTRACT.value,
                DeviationObject.LMS2_COLLATERAL.value,
            )
        ]
        pipeline = self._pipeline([record, opportunity, contract, *others])

        self._run(pipeline, self._item())

        self.assertEqual(len(contract.contexts), 1)
        self.assertEqual(contract.contexts[0].product_type, "Home Loan")
        self.assertEqual(contract.contexts[0].opportunity_url, OPP_URL)

    def test_ambiguity_skips_the_whole_item(self) -> None:
        record = FakeAdapter(
            DeviationObject.DEVIATION.value,
            Discovery(
                refs=(
                    DiscoveredRef(
                        kind=DeviationObject.OPPORTUNITY.value,
                        name="Opp",
                        url=OPP_URL,
                    ),
                )
            ),
        )
        opportunity = FakeAdapter(
            DeviationObject.OPPORTUNITY.value,
            Discovery(attributes={"product_type": "Home Loan"}),
        )
        contract = FakeAdapter(
            DeviationObject.CL_CONTRACT.value,
            Discovery(skip_reason="multiple matching CL contracts"),
        )
        others = [
            FakeAdapter(kind, Discovery())
            for kind in (
                DeviationObject.COLLATERAL.value,
                DeviationObject.LMS2_CL_CONTRACT.value,
                DeviationObject.LMS2_COLLATERAL.value,
            )
        ]
        pipeline = self._pipeline([record, opportunity, contract, *others])

        outcome = self._run(pipeline, self._item())
        self.assertIs(outcome, ExtractOutcome.SKIPPED)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIs(item.status, WorkItemStatus.SKIPPED)
        self.assertEqual(item.reason, "multiple matching CL contracts")

    def test_adapter_exception_becomes_a_skip(self) -> None:
        record = FakeAdapter(
            DeviationObject.DEVIATION.value,
            Discovery(
                refs=(
                    DiscoveredRef(
                        kind=DeviationObject.OPPORTUNITY.value,
                        name="Opp",
                        url=OPP_URL,
                    ),
                )
            ),
        )
        others = [
            FakeAdapter(kind, Discovery())
            for kind in (
                DeviationObject.CL_CONTRACT.value,
                DeviationObject.COLLATERAL.value,
                DeviationObject.LMS2_CL_CONTRACT.value,
                DeviationObject.LMS2_COLLATERAL.value,
            )
        ]
        pipeline = self._pipeline(
            [record, FailingAdapter(RuntimeError("boom")), *others]
        )

        with self.assertLogs("app.workflows.deviations_z02.extraction", "ERROR"):
            outcome = self._run(pipeline, self._item())
        self.assertIs(outcome, ExtractOutcome.SKIPPED)
        item = self.deps().items.require("deviations_z02", KEY)
        self.assertIn("internal error in opportunity", item.reason or "")

    def test_missing_opportunity_link_skips(self) -> None:
        record = FakeAdapter(DeviationObject.DEVIATION.value, Discovery())
        others = [
            FakeAdapter(kind, Discovery())
            for kind in (
                DeviationObject.OPPORTUNITY.value,
                DeviationObject.CL_CONTRACT.value,
                DeviationObject.COLLATERAL.value,
                DeviationObject.LMS2_CL_CONTRACT.value,
                DeviationObject.LMS2_COLLATERAL.value,
            )
        ]
        pipeline = self._pipeline([record, *others])

        outcome = self._run(pipeline, self._item())
        self.assertIs(outcome, ExtractOutcome.SKIPPED)
        self.assertIn("no Opportunity link", self.deps().items.require("deviations_z02", KEY).reason or "")

    def test_already_extracted_is_a_no_op(self) -> None:
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

    def test_force_re_extracts(self) -> None:
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
        record = FakeAdapter(
            DeviationObject.DEVIATION.value,
            Discovery(skip_reason="no Opportunity link"),
        )
        pipeline = self._pipeline([record], force=True)

        outcome = self._run(pipeline, deps.items.require("deviations_z02", KEY))
        self.assertIs(outcome, ExtractOutcome.SKIPPED)
        self.assertEqual(record.calls, 1)


if __name__ == "__main__":
    unittest.main()
