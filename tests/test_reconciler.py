"""Reconciler and closure resolver behaviour on synthetic samples."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable, Mapping

from app.core.errors import SessionExpired
from app.core.list_view import ListRow, ListSample, ListViewSpec
from app.core.models import WorkItem, utcnow
from app.core.repo.jobs import JobQuery, JobRepository
from app.core.repo.sync_runs import SyncRunRepository
from app.core.status import (
    MISSING_RECORD_URL_REASON,
    ClosureSource,
    ExtractOutcome,
    JobKind,
    SubmitOutcome,
    WorkItemStatus,
)
from app.core.workflow import JobLogger, Workflow
from app.jobs.auth import AuthGate
from app.pipeline.closure import ClosureResolver
from app.pipeline.reconciler import Reconciler
from app.pipeline.watcher import ListWatcher
from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02.catalog import FIELD_CATALOG
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
KEY = "Deviation-03112026-486382"
OPP = "https://org/lightning/r/Opportunity/006/view"


def row(key: str = KEY, approved: str | None = "4/11/2026 6:46 pm") -> ListRow:
    return ListRow(
        key=key,
        href=f"/lightning/r/a2f/{key}/view",
        columns={},
        approved_at=approved,
    )


def sample(*rows: ListRow, header: int | None = None) -> ListSample:
    return ListSample(
        captured_at=utcnow(),
        header_total=len(rows) if header is None else header,
        rows=rows,
    )


class NoExtraction:
    """Pipeline placeholder: the reconciler must never invoke extraction."""

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> ExtractOutcome:
        raise AssertionError("reconciler must not run pipelines")


class NoSubmission:
    """Pipeline placeholder: the reconciler must never invoke submission."""

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        raise AssertionError("reconciler must not run pipelines")


class ReconcilerTestCase(DbTestCase):
    def job_repo(self) -> JobRepository:
        """A job repository on this test's database."""
        return JobRepository(self.db)

    def workflow(self, mapped: Mapping[str, str] | None = None) -> Workflow:
        def map_row(_row: ListRow) -> Mapping[str, str]:
            return mapped or {}

        return Workflow(
            name=WORKFLOW,
            route="deviations",
            list_view=ListViewSpec(url="https://org/list", pattern=r"Deviation-\d+-\d+"),
            catalog=FIELD_CATALOG,
            adapters=AdapterRegistry([]),
            extraction=NoExtraction(),
            submission=NoSubmission(),
            map_row=map_row,
        )

    def build(
        self, mapped: Mapping[str, str] | None = None
    ) -> tuple[Reconciler, ClosureResolver, Workflow]:
        deps = self.deps()
        workflow = self.workflow(mapped)
        jobs = self.job_repo()
        closure = ClosureResolver(deps.items, jobs, deps.events)
        reconciler = Reconciler(
            workflow,
            deps.items,
            jobs,
            deps.attributes,
            SyncRunRepository(self.db),
            closure,
        )
        return reconciler, closure, workflow


class ReconcilerTests(ReconcilerTestCase):
    def test_new_rows_become_items_with_an_extract_job(self) -> None:
        reconciler, _closure, _workflow = self.build()
        run = reconciler.apply(sample(row(KEY), row("Deviation-2-2")))

        self.assertTrue(run.valid)
        self.assertEqual(run.added, 2)
        item = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.PRESENT)
        self.assertEqual(item.record_url, f"/lightning/r/a2f/{KEY}/view")
        self.assertEqual(item.approved_at, "4/11/2026 6:46 pm")
        jobs = self.job_repo()
        self.assertEqual(len([j for j in jobs.query(JobQuery(workflow=WORKFLOW)).jobs if j.kind is JobKind.EXTRACT]), 2)

    def test_missing_url_skip_is_retried_when_the_link_arrives(self) -> None:
        """A printable-first row gets a second extraction once its link renders (FR-3.9)."""
        deps = self.deps()
        deps.items.create_present(
            WORKFLOW,
            ListRow(key=KEY, href="", columns={}, approved_at=None),
            utcnow(),
        )
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(
            WORKFLOW,
            KEY,
            WorkItemStatus.SKIPPED,
            reason=MISSING_RECORD_URL_REASON,
        )

        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row()))

        item = deps.items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.PRESENT)
        self.assertIsNone(item.reason)
        self.assertEqual(item.record_url, f"/lightning/r/a2f/{KEY}/view")
        jobs = self.job_repo()
        queued = [
            job
            for job in jobs.query(JobQuery(workflow=WORKFLOW)).jobs
            if job.kind is JobKind.EXTRACT
        ]
        self.assertEqual(len(queued), 1)

    def test_other_skips_are_not_retried_when_a_link_arrives(self) -> None:
        """Only the missing-URL skip self-heals; ambiguity stays terminal."""
        deps = self.deps()
        deps.items.create_present(WORKFLOW, row(), utcnow())
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(
            WORKFLOW,
            KEY,
            WorkItemStatus.SKIPPED,
            reason="multiple LMS2 CL contracts",
        )

        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row()))

        item = deps.items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.SKIPPED)
        self.assertEqual(item.reason, "multiple LMS2 CL contracts")
        jobs = self.job_repo()
        queued = [
            job
            for job in jobs.query(JobQuery(workflow=WORKFLOW)).jobs
            if job.kind is JobKind.EXTRACT
        ]
        self.assertEqual(queued, [])

    def test_known_row_is_touched_and_attributes_are_mapped(self) -> None:
        reconciler, _closure, _workflow = self.build({"product_type": "Home Loan"})
        reconciler.apply(sample(row()))
        before = self.deps().items.require(WORKFLOW, KEY)

        run = reconciler.apply(sample(row()))
        after = self.deps().items.require(WORKFLOW, KEY)
        self.assertEqual(run.updated, 1)
        self.assertEqual(run.added, 0)
        self.assertGreaterEqual(after.last_seen, before.last_seen)
        self.assertEqual(
            self.deps().attributes.for_item(WORKFLOW, KEY)["product_type"], "Home Loan"
        )

    def test_approval_date_is_refreshed_from_a_later_sync(self) -> None:
        """SF adds the approval date after first sight; a sync must pick it up (FR-2.3).

        The date must also never be cleared when a later sample omits it.
        """
        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row(approved=None)))
        self.assertIsNone(self.deps().items.require(WORKFLOW, KEY).approved_at)

        reconciler.apply(sample(row(approved="4/11/2026 6:46 pm")))
        self.assertEqual(
            self.deps().items.require(WORKFLOW, KEY).approved_at,
            "4/11/2026 6:46 pm",
        )

        reconciler.apply(sample(row(approved=None)))
        self.assertEqual(
            self.deps().items.require(WORKFLOW, KEY).approved_at,
            "4/11/2026 6:46 pm",
        )

    def test_refresh_never_touches_editable_values(self) -> None:
        """A refresh may update attributes, never extracted/proposed field state (I4)."""
        reconciler, _closure, _workflow = self.build({"product_type": "Home Loan"})
        reconciler.apply(sample(row()))
        fields = self.deps().fields
        fields.set_extracted(WORKFLOW, KEY, {"tenure": "240"})
        fields.propose(WORKFLOW, KEY, {"tenure": "300"})

        reconciler.apply(sample(row()))

        stored = fields.get(WORKFLOW, KEY, "tenure")
        assert stored is not None
        self.assertEqual(stored.proposed, "300")
        self.assertEqual(stored.extracted, "240")

    def test_invalid_sample_changes_nothing(self) -> None:
        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row()))
        run = reconciler.apply(sample(row(), row("Deviation-2-2"), header=3))

        self.assertFalse(run.valid)
        self.assertIn("header total 3 != rows 2", run.warning or "")
        self.assertEqual(run.added, 0)
        self.assertEqual(run.updated, 0)
        self.assertEqual(run.closed, 0)
        self.assertIsNone(self.deps().items.get(WORKFLOW, "Deviation-2-2"))

    def test_missing_item_closes_as_external(self) -> None:
        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row()))
        deps = self.deps()
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow())

        run = reconciler.apply(sample())
        self.assertEqual(run.closed, 1)
        item = deps.items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.CLOSED)
        self.assertIs(item.source, ClosureSource.EXTERNAL)
        self.assertEqual(item.reason, "already_implemented")
        self.assertFalse(item.present)

    def test_missing_item_after_confirmed_implement_is_completed_by_us(self) -> None:
        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row()))
        deps = self.deps()
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow())
        deps.items.mark_execute_attempted(WORKFLOW, KEY, utcnow())
        deps.items.mark_execute_confirmed(WORKFLOW, KEY, utcnow())

        reconciler.apply(sample())
        item = deps.items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.COMPLETED)
        self.assertIs(item.source, ClosureSource.SYSTEM)
        self.assertIsNone(item.reason)

    def test_unconfirmed_implement_is_completed_with_a_flag(self) -> None:
        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row()))
        deps = self.deps()
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow())
        deps.items.mark_execute_attempted(WORKFLOW, KEY, utcnow())

        reconciler.apply(sample())
        item = deps.items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.COMPLETED)
        self.assertEqual(item.reason, "implement_unconfirmed")

    def test_reappearing_item_starts_a_new_epoch(self) -> None:
        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row()))
        reconciler.apply(sample())
        closed = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(closed.status, WorkItemStatus.CLOSED)

        reconciler.apply(sample(row()))
        back = self.deps().items.require(WORKFLOW, KEY)
        self.assertTrue(back.present)
        self.assertIs(back.status, WorkItemStatus.PRESENT)
        self.assertEqual(back.epoch, closed.epoch + 1)


class ClosureDuringLeaseTests(ReconcilerTestCase):
    def test_absent_while_leased_is_deferred_then_resolved(self) -> None:
        reconciler, closure, _workflow = self.build()
        reconciler.apply(sample(row()))
        deps = self.deps()
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow())

        job = self.job_repo().enqueue(WORKFLOW, JobKind.SUBMIT, KEY)
        self.job_repo().claim("w0", ttl_s=300)

        run = reconciler.apply(sample())
        self.assertEqual(run.closed, 0)
        pending = deps.items.require(WORKFLOW, KEY)
        self.assertIs(pending.status, WorkItemStatus.ABSENT_PENDING)
        self.assertFalse(pending.present)

        self.job_repo().complete(job.id)
        closure.release_lease(WORKFLOW, KEY)
        done = deps.items.require(WORKFLOW, KEY)
        self.assertIs(done.status, WorkItemStatus.CLOSED)
        self.assertIs(done.source, ClosureSource.EXTERNAL)


class AbsentNeedsReviewTests(ReconcilerTestCase):
    """A needs_review item that leaves the list must still close."""

    def _needs_review(self) -> None:
        """Create a present item and move it to needs_review."""
        reconciler, _closure, _workflow = self.build()
        reconciler.apply(sample(row()))
        deps = self.deps()
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(
            WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow()
        )
        deps.items.transition(
            WORKFLOW, KEY, WorkItemStatus.NEEDS_REVIEW, reason="rejected write"
        )

    def test_absent_needs_review_closes_on_the_first_cycle(self) -> None:
        """The closure path needs needs_review -> absent_pending."""
        self._needs_review()
        reconciler, _closure, _workflow = self.build()
        run = reconciler.apply(sample())
        self.assertEqual(run.closed, 1)
        item = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.CLOSED)
        self.assertIs(item.source, ClosureSource.EXTERNAL)
        self.assertFalse(item.present)
        self.assertIsNotNone(item.closed_at)

    def test_already_absent_needs_review_is_retried(self) -> None:
        """A failed first close must be retried instead of stranding the item."""
        self._needs_review()
        deps = self.deps()
        deps.items.set_absent(WORKFLOW, KEY, utcnow())
        reconciler, _closure, _workflow = self.build()
        run = reconciler.apply(sample())
        self.assertEqual(run.closed, 1)
        item = deps.items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.CLOSED)
        self.assertIs(item.source, ClosureSource.EXTERNAL)
        self.assertFalse(item.present)


class _FakeSource:
    """``SampleSource`` fake: counts open/sample/close and can fail on demand."""

    def __init__(
        self,
        samples: list[ListSample],
        *,
        fail_opens: int = 0,
        error: Exception | None = None,
    ) -> None:
        """Keep the samples to replay; ``fail_opens``/``error`` model auth and read faults."""
        self._samples = samples
        self._fail_opens = fail_opens
        self._error = error
        self._open = False
        self.attempts = 0
        self.opens = 0
        self.closes = 0
        self.calls = 0

    async def ensure_open(self) -> None:
        """Open once; a failure leaves the source closed so the next call retries."""
        if self._open:
            return
        self.attempts += 1
        if self._error is not None:
            raise self._error
        if self._fail_opens > 0:
            self._fail_opens -= 1
            raise SessionExpired("not logged in")
        self._open = True
        self.opens += 1

    async def sample(self) -> ListSample:
        """Replay the next sample; refuses to sample a page that was never opened."""
        if not self._open:
            raise AssertionError("sample() before ensure_open()")
        self.calls += 1
        return self._samples[min(self.calls - 1, len(self._samples) - 1)]

    async def close(self) -> None:
        """Drop the page; safe to call repeatedly."""
        self._open = False
        self.closes += 1


class ListWatcherTests(ReconcilerTestCase):
    def make(
        self, source: _FakeSource, *, interval: float = 30.0
    ) -> tuple[ListWatcher, AuthGate]:
        """Wire a watcher over the fake source on this test's database."""
        reconciler, _closure, workflow = self.build()
        deps = self.deps()
        auth = AuthGate(self.job_repo(), deps.events)
        return (
            ListWatcher(workflow, source, reconciler, deps.events, auth, interval),
            auth,
        )

    def test_refresh_once_opens_the_page_then_reuses_it(self) -> None:
        source = _FakeSource([sample(row())])
        watcher, _auth = self.make(source)

        async def scenario() -> None:
            first = await watcher.refresh_once()
            self.assertTrue(first.valid)
            await watcher.refresh_once()

        asyncio.run(scenario())
        self.assertEqual(source.opens, 1)
        self.assertEqual(source.calls, 2)

    def test_expired_open_pauses_and_reopens_once_after_resume(self) -> None:
        source = _FakeSource([sample(row())], fail_opens=1)
        watcher, auth = self.make(source, interval=0.01)

        async def scenario() -> None:
            task = asyncio.create_task(watcher.run_forever())
            await _wait_until(lambda: auth.paused, 5.0)
            await asyncio.sleep(0.1)  # a paused gate must not retry
            self.assertEqual(source.attempts, 1)
            auth.resume()
            await _wait_until(lambda: source.calls > 0, 5.0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        self.assertEqual(source.opens, 1)
        self.assertGreaterEqual(source.calls, 1)

    def test_concurrent_refreshes_share_one_page(self) -> None:
        source = _FakeSource([sample(row())])
        watcher, _auth = self.make(source)

        async def scenario() -> None:
            await asyncio.gather(watcher.refresh_once(), watcher.refresh_once())

        asyncio.run(scenario())
        self.assertEqual(source.opens, 1)
        self.assertEqual(source.calls, 2)

    def test_non_auth_failure_retries_at_the_interval(self) -> None:
        source = _FakeSource([sample(row())], error=RuntimeError("page detached"))
        watcher, auth = self.make(source, interval=0.02)

        async def scenario() -> None:
            task = asyncio.create_task(watcher.run_forever())
            await asyncio.sleep(0.15)
            self.assertFalse(task.done())
            self.assertFalse(auth.paused)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        self.assertGreaterEqual(source.attempts, 2)
        self.assertLessEqual(source.attempts, 12)

    def test_paused_gate_waits_before_sampling(self) -> None:
        reconciler, _closure, workflow = self.build()
        deps = self.deps()
        source = _FakeSource([sample(row())])
        auth = AuthGate(self.job_repo(), deps.events)
        watcher = ListWatcher(workflow, source, reconciler, deps.events, auth, 0.01)

        async def scenario() -> None:
            auth.pause("test")
            task = asyncio.create_task(watcher.run_forever())
            await asyncio.sleep(0.1)
            self.assertEqual(source.calls, 0)
            auth.resume()
            await _wait_until(lambda: source.calls > 0, 5.0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        self.assertEqual(source.opens, 1)
        self.assertEqual(source.closes, 1)


async def _wait_until(predicate: Callable[[], bool], timeout: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


if __name__ == "__main__":
    unittest.main()
