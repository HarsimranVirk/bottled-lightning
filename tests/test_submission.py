"""Submission pipeline: apply/validate, pre-read audit, rejection, idempotency."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Mapping, Sequence

from playwright.async_api import Page

from app.config import NetworkProfile, SubmissionTimeouts, TimeoutPolicy
from app.core.errors import TransientBrowserError
from app.core.field import FieldTarget
from app.core.job_logger import JobLogger
from app.core.list_view import ListRow
from app.core.models import PageRef, WorkItem, utcnow
from app.core.status import (
    FieldStatus,
    RefState,
    SubmitOutcome,
    WorkItemStatus,
    WriteOutcome,
)
from app.salesforce.adapters import AdapterBase, AdapterRegistry
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02 import REF_KINDS as DECLARED_REF_KINDS
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
        """Skip Playwright's impl-bound constructor and start alive."""
        self.closed = False

    def is_closed(self) -> bool:
        """Report the test-controlled liveness flag instead of asking a browser."""
        return self.closed


class FakeTabs:
    """Tab provider that hands out an inert page object."""

    async def new_page(self, url: str) -> Page:
        """Return a fake page (the adapters ignore the URL)."""
        return FakePage()

    async def close_page(self, page: Page) -> None:
        """No-op: the fake page has nothing to close."""


class CountingTabs(FakeTabs):
    """Tab provider that records the pages it hands out and closes."""

    def __init__(self) -> None:
        """Start with no pages opened."""
        self.opened: list[str] = []
        self.closed = 0

    async def new_page(self, url: str) -> Page:
        """Record the URL, then return the inert page."""
        self.opened.append(url)
        return await super().new_page(url)

    async def close_page(self, page: Page) -> None:
        """Count one closed page."""
        self.closed += 1


class FakeDeviationAdapter(DeviationRecordAdapter):
    """In-memory deviation record: records the click and the tick it reports."""

    def __init__(
        self, *, implemented: bool | None = False, confirm: bool = True
    ) -> None:
        """Seed the initial tick and whether the click should confirm it."""
        super().__init__("https://org", TimeoutPolicy())
        self.implemented = implemented
        self.confirm = confirm
        self.clicks = 0
        self.opened: list[str] = []

    async def open_record(self, tabs: TabProvider, record_url: str) -> Page:
        """Record the record URL and hand back a fake page."""
        self.opened.append(record_url)
        return FakePage()

    async def is_implemented(self, page: Page, log: JobLogger) -> bool | None:
        """Report the seeded tick."""
        return self.implemented

    async def implement(self, page: Page, log: JobLogger) -> bool:
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
        self.kill_after_read = False
        self.kill_after_write = False
        self.read_delay_s = 0.0
        self.write_delay_s = 0.0

    async def read(
        self, page: Page, targets: Sequence[FieldTarget], log: JobLogger
    ) -> dict[FieldTarget, str | None]:
        """Return the current in-memory value for each target, after any seeded delay."""
        self.reads += 1
        if self.read_delay_s:
            await asyncio.sleep(self.read_delay_s)
        if self.kill_after_read and isinstance(page, FakePage):
            page.closed = True
        return {target: self.current.get(target) for target in targets}

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str], log: JobLogger
    ) -> dict[FieldTarget, WriteOutcome]:
        """Apply each value unless the target is configured to reject it."""
        if self.write_delay_s:
            await asyncio.sleep(self.write_delay_s)
        results: dict[FieldTarget, WriteOutcome] = {}
        for target, value in values.items():
            outcome = self.outcomes.get(target, WriteOutcome.SAVED)
            results[target] = outcome
            if outcome is WriteOutcome.SAVED:
                self.current[target] = value
                self.writes[target] = value
        if self.kill_after_write and isinstance(page, FakePage):
            page.closed = True
        return results


class TinyTimeouts(TimeoutPolicy):
    """A policy with millisecond budgets so the timeout paths run fast in tests."""

    def __init__(self, *, read_ms: int, write_ms: int, total_ms: int) -> None:
        """Freeze the per-stage and whole-run budgets at millisecond values."""
        super().__init__()
        self._tiny = SubmissionTimeouts(
            profile=NetworkProfile.DEFAULT,
            action_ms=1_000,
            stage_read_ms=read_ms,
            stage_write_ms=write_ms,
            submission_ms=total_ms,
        )

    def current(self) -> SubmissionTimeouts:
        """Return the frozen millisecond budgets."""
        return self._tiny


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

    def setUp(self) -> None:
        """Use the shipped timeouts unless a test swaps in tiny budgets."""
        super().setUp()
        self.timeouts: TimeoutPolicy = TimeoutPolicy()

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
            ref_kinds=DECLARED_REF_KINDS,
            timeouts=self.timeouts,
        )

    def _run(
        self,
        pipeline: DeviationsZ02Submission,
        item: WorkItem,
        lines: list[str] | None = None,
        tabs: TabProvider | None = None,
    ) -> SubmitOutcome:
        """Run the pipeline on a fresh event loop, optionally capturing its log."""
        sink = [] if lines is None else lines

        def log(message: str) -> None:
            """Append one captured line."""
            sink.append(message)

        return asyncio.run(pipeline.run(item, tabs or FakeTabs(), log))

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

    def test_dead_page_during_read_is_transient(self) -> None:
        """A tab that dies mid-read raises instead of trusting its empty values."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        adapters = self._adapters(self._current())
        opportunity = adapters.get(DeviationObject.OPPORTUNITY.value)
        assert isinstance(opportunity, FakeWriteAdapter)
        opportunity.kill_after_read = True
        pipeline = self._pipeline(adapters)

        with self.assertRaises(TransientBrowserError):
            self._run(pipeline, item)

        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.SUBMITTING)

    def test_dead_page_during_apply_is_transient(self) -> None:
        """A tab that dies mid-apply aborts before the next object is written."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        adapters = self._adapters(self._current())
        opportunity = adapters.get(DeviationObject.OPPORTUNITY.value)
        assert isinstance(opportunity, FakeWriteAdapter)
        opportunity.kill_after_write = True
        contract = adapters.get(DeviationObject.CL_CONTRACT.value)
        assert isinstance(contract, FakeWriteAdapter)
        pipeline = self._pipeline(adapters)
        lines: list[str] = []

        with self.assertRaises(TransientBrowserError):
            self._run(pipeline, item, lines)

        # The dead tab is reported as such, and the remaining objects are not touched.
        self.assertIn("apply: opportunity: page closed during the write", lines)
        self.assertEqual(contract.writes, {})
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.APPLYING)

    def test_write_timeout_records_unknown_and_keeps_writing(self) -> None:
        """A group that overruns is recorded UNKNOWN, and later objects are still written."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        adapters = self._adapters(self._current())
        opportunity = adapters.get(DeviationObject.OPPORTUNITY.value)
        assert isinstance(opportunity, FakeWriteAdapter)
        opportunity.write_delay_s = 0.2
        contract = adapters.get(DeviationObject.CL_CONTRACT.value)
        assert isinstance(contract, FakeWriteAdapter)
        self.timeouts = TinyTimeouts(read_ms=5_000, write_ms=50, total_ms=30_000)
        pipeline = self._pipeline(adapters)
        lines: list[str] = []

        outcome = self._run(pipeline, item, lines)

        self.assertIs(outcome, SubmitOutcome.FAILED)
        self.assertIn(
            "apply: opportunity: write did not finish within", "\n".join(lines)
        )
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIn("opportunity/Loan Amount=unknown", fresh.reason or "")
        # The overrun costs one group, not the submission's other objects.
        self.assertTrue(contract.writes)

    def test_whole_run_timeout_fails_with_the_budget(self) -> None:
        """The whole-run budget stops a merely slow job and names the budget."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        adapters = self._adapters(self._current())
        opportunity = adapters.get(DeviationObject.OPPORTUNITY.value)
        assert isinstance(opportunity, FakeWriteAdapter)
        opportunity.read_delay_s = 0.2
        self.timeouts = TinyTimeouts(read_ms=5_000, write_ms=5_000, total_ms=50)
        pipeline = self._pipeline(adapters)

        outcome = self._run(pipeline, item)

        self.assertIs(outcome, SubmitOutcome.FAILED)
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertIn("submission did not finish within", fresh.reason or "")

    def test_validation_reopens_each_record_page(self) -> None:
        """The read-back loads fresh pages instead of re-reading the edited tabs."""
        item = self._item()
        self._refs()
        self._seed({"loan_amount": "14,50,000"})
        tabs = CountingTabs()
        pipeline = self._pipeline(self._adapters(self._current()))
        lines: list[str] = []

        outcome = self._run(pipeline, item, lines, tabs)

        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        loan_amount = next(
            spec for spec in FIELD_CATALOG if spec.key == "loan_amount"
        )
        kinds = {target.object_kind for target in loan_amount.targets}
        # One page per object for precheck/apply, one fresh page per object for the
        # read-back, plus the deviation record page for the final action — all closed.
        self.assertEqual(len(set(tabs.opened)), len(kinds))
        self.assertEqual(len(tabs.opened), 2 * len(kinds))
        self.assertEqual(tabs.closed, 2 * len(kinds) + 1)
        self.assertIn("readback: reading opportunity", "\n".join(lines))

    def test_job_log_names_every_phase_and_object(self) -> None:
        """The persisted log names the phase, object and validation result."""
        item = self._item()
        self._refs()
        self._seed(
            {
                "loan_amount": "14,50,000",
                "tenure": "180",
                "emi_incl_hffc": "18,585",
            }
        )
        pipeline = self._pipeline(self._adapters(self._current()))
        lines: list[str] = []

        outcome = self._run(pipeline, item, lines)

        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        joined = "\n".join(lines)
        for expected in (
            "phase: applying",
            "precheck: reading opportunity",
            "apply: cl_contract (3 target(s))",
            "phase: validating",
            "readback: reading cl_contract",
            "validated: loan_amount",
            "phase: executing",
            "execute: deviation: record page opened",
        ):
            self.assertIn(expected, joined)

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

    def test_missing_page_link_refuses_before_writing(self) -> None:
        """A missing object link refuses the run before any write or status change."""
        item = self._item()
        self._refs(missing=DeviationObject.LMS2_CL_CONTRACT.value)
        self._seed({"loan_amount": "14,50,000"})
        current = self._current()
        adapters = self._adapters(current)
        pipeline = self._pipeline(adapters)
        lines: list[str] = []

        outcome = self._run(pipeline, item, lines)

        self.assertIs(outcome, SubmitOutcome.FAILED)
        # Nothing was attempted, so the item keeps its status: the API refuses this
        # case up front, and the pipeline is only the safety net.
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.READY)
        self.assertIn("missing the lms2 cl contract page link", "\n".join(lines))
        for kind in REF_KINDS:
            if kind == DeviationObject.LMS2_CL_CONTRACT.value:
                continue
            adapter = adapters.get(kind)
            assert isinstance(adapter, FakeWriteAdapter)
            self.assertEqual(adapter.writes, {})

    def test_absent_link_reports_its_plain_reason(self) -> None:
        """A positively absent object is refused with the operator-facing sentence."""
        item = self._item()
        self.deps().refs.replace(
            WORKFLOW,
            KEY,
            [
                PageRef(
                    workflow=WORKFLOW,
                    item=KEY,
                    kind=kind,
                    name=kind,
                    url="" if kind == DeviationObject.COLLATERAL.value else f"https://org/{kind}",
                    state=(
                        RefState.ABSENT
                        if kind == DeviationObject.COLLATERAL.value
                        else RefState.FOUND
                    ),
                    reason=(
                        "No collateral attached to this opportunity"
                        if kind == DeviationObject.COLLATERAL.value
                        else None
                    ),
                )
                for kind in REF_KINDS
            ],
        )
        self._seed({"loan_amount": "14,50,000"})
        pipeline = self._pipeline(self._adapters(self._current()))
        lines: list[str] = []

        outcome = self._run(pipeline, item, lines)

        self.assertIs(outcome, SubmitOutcome.FAILED)
        self.assertIn(
            "No collateral attached to this opportunity", "\n".join(lines)
        )
        fresh = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(fresh.status, WorkItemStatus.READY)

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
