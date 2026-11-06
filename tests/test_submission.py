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
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02.adapters.deviation_record import (
    DeviationRecordAdapter,
)
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
    "roi": "11.95",
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


class FakeDeviationAdapter(DeviationRecordAdapter):
    """In-memory deviation record: records the click and the tick it reports."""

    def __init__(
        self, *, implemented: bool | None = False, confirm: bool = True
    ) -> None:
        """Seed the initial tick and whether the click should confirm it."""
        super().__init__("https://org", 1000)
        self.implemented = implemented
        self.confirm = confirm
        self.clicks = 0
        self.opened: list[str] = []

    async def open_record(self, tabs: TabProvider, record_url: str) -> Page:
        """Record the record URL and hand back a fake page."""
        self.opened.append(record_url)
        return FakePage()

    async def is_implemented(self, page: Page) -> bool | None:
        """Report the seeded tick."""
        return self.implemented

    async def implement(self, page: Page) -> bool:
        """Count the click; turn the tick on only when ``confirm`` is set."""
        self.clicks += 1
        if self.confirm:
            self.implemented = True
            return True
        return False


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
        deviation: FakeDeviationAdapter | None = None,
    ) -> AdapterRegistry:
        """Build one fake adapter per object kind plus the deviation record."""
        adapters: list[AdapterBase] = [
            FakeWriteAdapter(
                kind,
                {target: value for target, value in current.items() if target.object_kind == kind},
                outcomes,
            )
            for kind in REF_KINDS
            if kind != missing
        ]
        adapters.append(deviation or FakeDeviationAdapter())
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
        )

    def _run(
        self, pipeline: DeviationsZ02Submission, item: WorkItem
    ) -> SubmitOutcome:
        """Run the pipeline on a fresh event loop."""
        return asyncio.run(pipeline.run(item, FakeTabs(), lambda _message: None))

    def test_apply_and_validate_marks_fields_applied(self) -> None:
        """A clean run writes every target, validates and implements."""
        item = self._item()
        self._refs()
        self._seed(
            {"loan_amount": "14,50,000", "emi_incl_hffc": "18,585"}
        )
        current = self._current()
        adapters = self._adapters(current)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.EXECUTING)
        self.assertIsNotNone(fresh.execute_attempted_at)
        self.assertIsNotNone(fresh.execute_confirmed_at)
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

        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.EXECUTING)
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

        self.assertIs(outcome, SubmitOutcome.COMPLETED)
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

        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        for kind in REF_KINDS:
            adapter = adapters.get(kind)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertEqual(adapter.writes, {})
        fields = self.deps().fields.for_item(WORKFLOW, KEY)
        self.assertEqual(fields["loan_amount"].applied, "1450000")


    def test_already_implemented_is_external(self) -> None:
        """A pre-existing tick is not claimed as our implementation."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        deviation = FakeDeviationAdapter(implemented=True)
        adapters = self._adapters(self._current(), deviation=deviation)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.ALREADY_CLOSED)
        self.assertEqual(deviation.clicks, 0)
        self.assertEqual(deviation.opened, [f"/lightning/r/a2f/{KEY}/view"])
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIsNone(fresh.execute_attempted_at)
        self.assertIsNone(fresh.execute_confirmed_at)

    def test_confirmed_implement_sets_both_timestamps(self) -> None:
        """A confirmed click records the attempt and the observation."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        deviation = FakeDeviationAdapter()
        adapters = self._adapters(self._current(), deviation=deviation)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        self.assertEqual(deviation.clicks, 1)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.EXECUTING)
        self.assertIsNotNone(fresh.execute_attempted_at)
        self.assertIsNotNone(fresh.execute_confirmed_at)

    def test_unconfirmed_implement_parks_for_review(self) -> None:
        """A click without the tick leaves the item for review with the attempt kept."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        deviation = FakeDeviationAdapter(confirm=False)
        adapters = self._adapters(self._current(), deviation=deviation)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.FAILED)
        self.assertEqual(deviation.clicks, 1)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertIsNotNone(fresh.execute_attempted_at)
        self.assertIsNone(fresh.execute_confirmed_at)
        self.assertIn("did not turn on", fresh.reason or "")

    def test_missing_record_url_fails_before_the_final_action(self) -> None:
        """Without a record link the deviation page cannot be opened."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        conn = self.db.connect()
        conn.execute(
            "UPDATE work_items SET record_url = NULL WHERE workflow = ? AND item_key = ?",
            [WORKFLOW, KEY],
        )
        conn.commit()
        adapters = self._adapters(self._current())
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.FAILED)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIn("no deviation record URL", fresh.reason or "")

    def test_resume_from_executing_skips_the_write_phase(self) -> None:
        """A requeued job that already validated only finishes the final action."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        deps = self.deps()
        for status in (
            WorkItemStatus.SUBMITTING,
            WorkItemStatus.APPLYING,
            WorkItemStatus.VALIDATING,
            WorkItemStatus.EXECUTING,
        ):
            deps.items.transition(WORKFLOW, KEY, status)
        deps.items.mark_execute_attempted(WORKFLOW, KEY, utcnow())
        adapters = self._adapters(self._current())
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        for kind in REF_KINDS:
            adapter = adapters.get(kind)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertEqual(adapter.reads, 0)
            self.assertEqual(adapter.writes, {})
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIsNotNone(fresh.execute_confirmed_at)


if __name__ == "__main__":
    unittest.main()
