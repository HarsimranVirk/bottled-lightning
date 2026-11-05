"""Submission pipeline: apply/validate, pre-read audit, rejection, idempotency."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Mapping, Sequence

from playwright.async_api import Page

from app.core.field import FieldTarget
from app.core.list_view import ListRow
from app.core.models import PageRef, WorkItem, utcnow
from app.core.status import FieldStatus, SubmitOutcome, WorkItemStatus, WriteOutcome
from app.salesforce.adapters import AdapterBase, AdapterRegistry
from app.workflows.deviations_z02.catalog import FIELD_CATALOG, DeviationObject
from app.workflows.deviations_z02.submission import DeviationsZ02Submission
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
KEY = "Deviation-28102026-484106"
REF_KINDS = (
    DeviationObject.OPPORTUNITY.value,
    DeviationObject.CL_CONTRACT.value,
    DeviationObject.COLLATERAL.value,
    DeviationObject.LMS2_CL_CONTRACT.value,
    DeviationObject.LMS2_COLLATERAL.value,
)
EXTRACTED = {
    "loan_amount": "13,00,000",
    "property_value": "22,50,000",
    "tenure": "180",
    "emi_incl_hffc": "16,256",
}


class FakePage(Page):
    """A Page stand-in; the fake adapters never touch it."""

    def __init__(self) -> None:
        """Skip Playwright's impl-bound constructor."""


class FakeTabs:
    """Tab provider that hands out an inert page object."""

    async def new_page(self, url: str) -> Page:
        """Return a fake page (the adapters ignore the URL)."""
        return FakePage()

    async def close_page(self, page: Page) -> None:
        """No-op: the fake page has nothing to close."""


class FakeWriteAdapter(AdapterBase):
    """In-memory adapter: records writes and can reject selected targets."""

    def __init__(
        self,
        kind: str,
        current: Mapping[FieldTarget, str],
        outcomes: Mapping[FieldTarget, WriteOutcome] | None = None,
    ) -> None:
        """Seed current values and optional forced outcomes."""
        self.kind = kind
        self.current = dict(current)
        self.outcomes = dict(outcomes or {})
        self.writes: dict[FieldTarget, str] = {}
        self.reads = 0

    async def read(
        self, page: Page, targets: Sequence[FieldTarget]
    ) -> dict[FieldTarget, str | None]:
        """Return the current in-memory value for each target."""
        self.reads += 1
        return {target: self.current.get(target) for target in targets}

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str]
    ) -> dict[FieldTarget, WriteOutcome]:
        """Apply each value unless the target is configured to reject it."""
        results: dict[FieldTarget, WriteOutcome] = {}
        for target, value in values.items():
            outcome = self.outcomes.get(target, WriteOutcome.SAVED)
            results[target] = outcome
            if outcome is WriteOutcome.SAVED:
                self.current[target] = value
                self.writes[target] = value
        return results


def _targets(kind: str) -> list[FieldTarget]:
    """All catalogue targets that live on one object kind."""
    return [
        target
        for spec in FIELD_CATALOG
        for target in spec.targets
        if target.object_kind == kind
    ]


class SubmissionTests(DbTestCase):
    """Submission pipeline behaviour with in-memory adapters."""

    def _item(self) -> WorkItem:
        """Create a ready item with the extraction marker set."""
        deps = self.deps()
        deps.items.create_present(
            WORKFLOW,
            ListRow(
                key=KEY,
                href=f"/lightning/r/a2f/{KEY}/view",
                columns={},
                approved_at=None,
            ),
            utcnow(),
        )
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        return deps.items.transition(
            WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow()
        )

    def _refs(self, missing: str | None = None) -> None:
        """Store one page ref per object kind, optionally omitting one."""
        self.deps().refs.replace(
            WORKFLOW,
            KEY,
            [
                PageRef(
                    workflow=WORKFLOW,
                    item=KEY,
                    kind=kind,
                    name=kind,
                    url=f"https://org/{kind}",
                )
                for kind in REF_KINDS
                if kind != missing
            ],
        )

    def _seed(
        self,
        proposed: Mapping[str, str],
        *,
        applied: Mapping[str, str] | None = None,
    ) -> None:
        """Seed extracted values, proposed edits and optional applied truth."""
        deps = self.deps()
        deps.fields.set_extracted(WORKFLOW, KEY, EXTRACTED)
        deps.fields.propose(WORKFLOW, KEY, proposed)
        for field_key, value in (applied or {}).items():
            deps.fields.mark_applied(WORKFLOW, KEY, field_key, value)

    def _current(
        self,
        overrides: Mapping[FieldTarget, str] | None = None,
        *,
        applied: Mapping[str, str] | None = None,
    ) -> dict[FieldTarget, str]:
        """Build the current SF value for every target from the extracted values."""
        current: dict[FieldTarget, str] = {}
        for spec in FIELD_CATALOG:
            if applied is not None and spec.key in applied:
                value = applied[spec.key]
            else:
                value = EXTRACTED[spec.key]
            for target in spec.targets:
                current[target] = value
        if overrides:
            current.update(overrides)
        return current

    def _adapters(
        self,
        current: Mapping[FieldTarget, str],
        outcomes: Mapping[FieldTarget, WriteOutcome] | None = None,
        missing: str | None = None,
    ) -> AdapterRegistry:
        """Build one fake adapter per object kind."""
        adapters = [
            FakeWriteAdapter(
                kind,
                {target: value for target, value in current.items() if target.object_kind == kind},
                outcomes,
            )
            for kind in REF_KINDS
            if kind != missing
        ]
        return AdapterRegistry(adapters)

    def _pipeline(self, adapters: AdapterRegistry) -> DeviationsZ02Submission:
        """Build the submission pipeline on this test's repositories."""
        deps = self.deps()
        return DeviationsZ02Submission(
            WORKFLOW,
            deps.items,
            deps.fields,
            deps.refs,
            deps.events,
            adapters,
            FIELD_CATALOG,
            final_action=False,
        )

    def _run(
        self, pipeline: DeviationsZ02Submission, item: WorkItem
    ) -> SubmitOutcome:
        """Run the pipeline on a fresh event loop."""
        return asyncio.run(pipeline.run(item, FakeTabs(), lambda _message: None))

    def test_apply_and_validate_marks_fields_applied(self) -> None:
        """A clean run writes every target, validates and returns validated."""
        item = self._item()
        self._refs()
        self._seed(
            {"loan_amount": "14,50,000", "emi_incl_hffc": "18,585"}
        )
        current = self._current()
        adapters = self._adapters(current)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.VALIDATED)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.READY)
        self.assertEqual(fresh.reason, "validated; final action disabled")
        fields = self.deps().fields.for_item(WORKFLOW, KEY)
        self.assertEqual(fields["loan_amount"].applied, "1450000")
        self.assertEqual(fields["emi_incl_hffc"].applied, "18585")
        self.assertIs(fields["loan_amount"].status, FieldStatus.APPLIED)
        self.assertIs(fields["emi_incl_hffc"].status, FieldStatus.APPLIED)
        for kind in (
            DeviationObject.OPPORTUNITY.value,
            DeviationObject.CL_CONTRACT.value,
            DeviationObject.LMS2_CL_CONTRACT.value,
        ):
            adapter = adapters.get(kind)
            self.assertIsInstance(adapter, FakeWriteAdapter)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertTrue(adapter.writes, f"{kind} should have been written")
        cl_adapter = adapters.get(DeviationObject.CL_CONTRACT.value)
        assert isinstance(cl_adapter, FakeWriteAdapter)
        self.assertEqual(len(cl_adapter.writes), 2)

    def test_pre_read_does_not_block_the_write(self) -> None:
        """A changed current value is audited but does not abort the write."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        opportunity_target = _targets(DeviationObject.OPPORTUNITY.value)[0]
        current = self._current({opportunity_target: "15,00,000"})
        adapters = self._adapters(current)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.VALIDATED)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.READY)
        for kind in (
            DeviationObject.OPPORTUNITY.value,
            DeviationObject.CL_CONTRACT.value,
            DeviationObject.LMS2_CL_CONTRACT.value,
        ):
            adapter = adapters.get(kind)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertTrue(adapter.writes, f"{kind} should still have been written")
        events = self.deps().events.recent(WORKFLOW, KEY)
        precheck = next(
            (detail for kind, _item, _at, detail in events if kind == "submit_precheck"),
            None,
        )
        self.assertIsNotNone(precheck)
        self.assertIn("15,00,000", precheck or "")

    def test_empty_proposal_is_not_written(self) -> None:
        """A blank field is skipped even if an empty proposal reached the database."""
        item = self._item()
        self._refs()
        self._seed(
            {"loan_amount": "14,50,000", "emi_incl_hffc": "18,585"}
        )
        self.deps().fields.propose(WORKFLOW, KEY, {"loan_amount": ""})
        current = self._current()
        adapters = self._adapters(current)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.VALIDATED)
        emi_target = next(
            target
            for target in _targets(DeviationObject.OPPORTUNITY.value)
            if target.label.startswith("EMIs")
        )
        opportunity = adapters.get(DeviationObject.OPPORTUNITY.value)
        assert isinstance(opportunity, FakeWriteAdapter)
        self.assertEqual(set(opportunity.writes), {emi_target})
        for kind in (
            DeviationObject.CL_CONTRACT.value,
            DeviationObject.LMS2_CL_CONTRACT.value,
        ):
            adapter = adapters.get(kind)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertEqual(adapter.writes, {})

    def test_rejected_write_parks_for_review(self) -> None:
        """A rejected target fails the field and leaves the item for review."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        current = self._current()
        contract_target = next(
            target
            for target in _targets(DeviationObject.CL_CONTRACT.value)
            if target.label == "Loan Amount"
        )
        adapters = self._adapters(
            current, {contract_target: WriteOutcome.REJECTED}
        )
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.FAILED)
        fields = self.deps().fields.for_item(WORKFLOW, KEY)
        self.assertIs(fields["loan_amount"].status, FieldStatus.REJECTED)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.NEEDS_REVIEW)

    def test_missing_page_link_fails_before_writing(self) -> None:
        """A missing object link cannot satisfy every target, so nothing is written."""
        item = self._item()
        self._refs(missing=DeviationObject.LMS2_CL_CONTRACT.value)
        self._seed({"loan_amount": "14,50,000"})
        current = self._current()
        adapters = self._adapters(current)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.FAILED)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertIn("missing lms2_cl_contract", fresh.reason or "")
        for kind in REF_KINDS:
            if kind == DeviationObject.LMS2_CL_CONTRACT.value:
                continue
            adapter = adapters.get(kind)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertEqual(adapter.writes, {})

    def test_already_closed_skips_all_writes(self) -> None:
        """An absent item is a clean terminal outcome, not a write."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        self.deps().items.set_absent(WORKFLOW, KEY, utcnow())
        current = self._current()
        adapters = self._adapters(current)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.ALREADY_CLOSED)
        for kind in REF_KINDS:
            adapter = adapters.get(kind)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertEqual(adapter.writes, {})

    def test_retry_after_crash_does_not_double_write(self) -> None:
        """Applied + current values are treated as done, not as a conflict."""
        item = self._item()
        self._refs()
        self._seed(
            {"loan_amount": "14,50,000"},
            applied={"loan_amount": "1450000"},
        )
        current = self._current(applied={"loan_amount": "14,50,000"})
        adapters = self._adapters(current)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.VALIDATED)
        for kind in REF_KINDS:
            adapter = adapters.get(kind)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertEqual(adapter.writes, {})
        fields = self.deps().fields.for_item(WORKFLOW, KEY)
        self.assertEqual(fields["loan_amount"].applied, "1450000")


if __name__ == "__main__":
    unittest.main()
