"""Worker and dispatcher behaviour with fake pipelines (no browser)."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable, Mapping

from playwright.async_api import Page

from app.config import Settings
from app.core.errors import SessionExpired, TransientBrowserError
from app.core.list_view import ListRow, ListViewSpec
from app.core.models import Job, WorkItem, utcnow
from app.core.registry import WorkflowRegistry
from app.core.repo.events import EventRepository
from app.core.repo.jobs import JobRepository
from app.core.status import (
    ExtractOutcome,
    JobKind,
    JobStatus,
    Phase,
    SubmitOutcome,
)
from app.core.workflow import (
    JobLogger,
    Workflow,
)
from app.jobs.auth import AuthGate
from app.jobs.dispatcher import Dispatcher
from app.jobs.worker import Worker
from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02.catalog import FIELD_CATALOG
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"


class FakeTabs:
    """Tab sessions that record cleanup instead of touching a browser."""
    def __init__(self) -> None:
        """Start with nothing closed."""
        self.closed = 0

    async def new_page(self, url: str) -> Page:
        """A fake pipeline must not open tabs."""
        raise AssertionError("fake pipeline must not open tabs")

    async def close_page(self, page: Page) -> None:
        """A fake pipeline must not close tabs."""
        raise AssertionError("fake pipeline must not close tabs")

    async def close_all(self) -> None:
        """Record that the worker cleaned up the tab group."""
        self.closed += 1


class FakeTabFactory:
    """Hands out fake tab groups so the worker can be tested."""
    def __init__(self) -> None:
        """Start with no groups."""
        self.groups: list[FakeTabs] = []

    def new_tab_group(self) -> FakeTabs:
        """Record and return a new fake group."""
        group = FakeTabs()
        self.groups.append(group)
        return group


class FakeExtraction:
    """Extraction pipeline returning a fixed outcome or raising."""
    def __init__(
        self, outcome: ExtractOutcome, error: Exception | None = None
    ) -> None:
        """Store the outcome and optional error."""
        self.outcome = outcome
        self.error = error
        self.calls = 0

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> ExtractOutcome:
        """Log, optionally raise, and return the configured outcome."""
        self.calls += 1
        log("fake extraction")
        if self.error is not None:
            raise self.error
        return self.outcome


class FakeSubmission:
    """Submission pipeline returning a fixed outcome."""
    def __init__(self, outcome: SubmitOutcome) -> None:
        """Store the configured outcome."""
        self.outcome = outcome
        self.calls = 0

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """Log and return the configured outcome."""
        self.calls += 1
        log("fake submission")
        return self.outcome


def make_workflow(
    extraction: FakeExtraction, submission: FakeSubmission
) -> Workflow:
    """Build a workflow around the fake pipelines."""
    def map_row(row: ListRow) -> Mapping[str, str]:
        """No list columns are mapped for the fake workflow."""
        return {}

    return Workflow(
        name=WORKFLOW,
        route="deviations",
        list_view=ListViewSpec(url="https://example/list", pattern=r"Deviation-\d+-\d+"),
        catalog=FIELD_CATALOG,
        adapters=AdapterRegistry([]),
        extraction=extraction,
        submission=submission,
        map_row=map_row,
    )


class JobTestCase(DbTestCase):
    """Shared fixtures for worker and dispatcher tests."""
    def settings(self) -> Settings:
        """Settings with a tiny poll interval for fast tests."""
        return Settings(
            org_base="https://example",
            data_dir=self.tmp_path,
            db_path=self.tmp_path / "app.db",
            workers=2,
            refresh_interval_s=30.0,
            request_timeout_ms=1000,
            login_wait_s=1,
            headless=True,
            update_policy="auto",
            deviations_z02_list_url="https://example/list",
            deviations_z02_pattern=r"Deviation-\d+-\d+",
        )

    def create_item(self, key: str = "Deviation-1-1") -> WorkItem:
        """Create a present item to attach jobs to."""
        return self.deps().items.create_present(
            WORKFLOW,
            ListRow(
                key=key,
                href=f"/lightning/r/a2f/{key}/view",
                columns={},
                approved_at=None,
            ),
            utcnow(),
        )

    def build(
        self,
        extraction: FakeExtraction,
        submission: FakeSubmission,
        *,
        name: str = "w0",
    ) -> tuple[Worker, JobRepository, AuthGate, FakeTabFactory]:
        """Wire a worker with fake pipelines and tab groups."""
        deps = self.deps()
        jobs = JobRepository(self.db)
        events = EventRepository(self.db)
        auth = AuthGate(jobs, events)
        registry = WorkflowRegistry()
        registry.register(make_workflow(extraction, submission))
        tabs = FakeTabFactory()
        worker = Worker(
            name,
            registry,
            deps.items,
            jobs,
            events,
            auth,
            tabs,
            lease_ttl_s=60,
        )
        return worker, jobs, auth, tabs


class WorkerTests(JobTestCase):
    """Outcome-to-status mapping, retries, auth parking and cleanup."""
    def run_job(self, job: Job, worker: Worker, jobs: JobRepository) -> None:
        """Execute one claimed job on a fresh event loop."""
        asyncio.run(worker.execute(job))

    def test_extracted_job_succeeds(self) -> None:
        """A successful extraction completes the job, logs every phase and closes tabs."""
        self.create_item()
        worker, jobs, _auth, tabs = self.build(
            FakeExtraction(ExtractOutcome.EXTRACTED), FakeSubmission(SubmitOutcome.COMPLETED)
        )
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, "Deviation-1-1")
        claimed = jobs.claim("w0", ttl_s=60)
        assert claimed is not None
        self.run_job(claimed, worker, jobs)

        done = jobs.require(job.id)
        self.assertIs(done.status, JobStatus.SUCCEEDED)
        self.assertIs(done.phase, Phase.EXTRACT)
        self.assertEqual(jobs.require(job.id).status, JobStatus.SUCCEEDED)
        logs = jobs.logs(job.id)
        self.assertEqual(logs[0], "extract start: deviations_z02/Deviation-1-1")
        self.assertIn("fake extraction", logs)
        self.assertEqual(logs[-1], "done: extracted")
        self.assertEqual(tabs.groups[0].closed, 1)

    def test_skipped_job_succeeds(self) -> None:
        """A skip is a clean terminal outcome, not a failure."""
        self.create_item()
        worker, jobs, _auth, _tabs = self.build(
            FakeExtraction(ExtractOutcome.SKIPPED), FakeSubmission(SubmitOutcome.COMPLETED)
        )
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, "Deviation-1-1")
        claimed = jobs.claim("w0", ttl_s=60)
        assert claimed is not None
        self.run_job(claimed, worker, jobs)
        self.assertIs(jobs.require(claimed.id).status, JobStatus.SUCCEEDED)

    def test_failed_extraction_retries_once(self) -> None:
        """A failed extraction is requeued once, then marked failed."""
        self.create_item()
        worker, jobs, _auth, tabs = self.build(
            FakeExtraction(ExtractOutcome.FAILED), FakeSubmission(SubmitOutcome.COMPLETED)
        )
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, "Deviation-1-1")
        first = jobs.claim("w0", ttl_s=60)
        assert first is not None
        self.run_job(first, worker, jobs)
        self.assertIs(jobs.require(first.id).status, JobStatus.QUEUED)

        second = jobs.claim("w0", ttl_s=60)
        assert second is not None
        self.run_job(second, worker, jobs)
        self.assertIs(jobs.require(first.id).status, JobStatus.FAILED)
        self.assertEqual(len(tabs.groups), 2)

    def test_session_expiry_parks_the_job_and_pauses(self) -> None:
        """Expiry parks the job as blocked_auth and pauses dispatch."""
        self.create_item()
        worker, jobs, auth, _tabs = self.build(
            FakeExtraction(ExtractOutcome.EXTRACTED, error=SessionExpired("login")),
            FakeSubmission(SubmitOutcome.COMPLETED),
        )
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, "Deviation-1-1")
        claimed = jobs.claim("w0", ttl_s=60)
        assert claimed is not None
        self.run_job(claimed, worker, jobs)

        self.assertIs(jobs.require(claimed.id).status, JobStatus.BLOCKED_AUTH)
        self.assertTrue(auth.paused)

    def test_transient_error_is_retryable(self) -> None:
        """Transient browser errors requeue instead of failing."""
        self.create_item()
        worker, jobs, _auth, _tabs = self.build(
            FakeExtraction(
                ExtractOutcome.EXTRACTED, error=TransientBrowserError("nav timeout")
            ),
            FakeSubmission(SubmitOutcome.COMPLETED),
        )
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, "Deviation-1-1")
        claimed = jobs.claim("w0", ttl_s=60)
        assert claimed is not None
        self.run_job(claimed, worker, jobs)
        again = jobs.require(claimed.id)
        self.assertIs(again.status, JobStatus.QUEUED)
        self.assertIn("nav timeout", again.error or "")

    def test_unexpected_error_fails_the_job(self) -> None:
        """An unexpected exception fails the job and is logged, never crashing the loop."""
        self.create_item()
        worker, jobs, _auth, _tabs = self.build(
            FakeExtraction(ExtractOutcome.EXTRACTED, error=RuntimeError("boom")),
            FakeSubmission(SubmitOutcome.COMPLETED),
        )
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, "Deviation-1-1")
        claimed = jobs.claim("w0", ttl_s=60)
        assert claimed is not None
        with self.assertLogs("app.jobs.worker", "ERROR"):
            self.run_job(claimed, worker, jobs)
        failed = jobs.require(claimed.id)
        self.assertIs(failed.status, JobStatus.FAILED)
        self.assertIn("RuntimeError", failed.error or "")

    def test_submit_completed_and_already_closed_succeed(self) -> None:
        """Both successful submission endings complete the job."""
        for outcome in (SubmitOutcome.COMPLETED, SubmitOutcome.ALREADY_CLOSED):
            with self.subTest(outcome=outcome):
                self.create_item(f"Deviation-{outcome.value}-1")
                worker, jobs, _auth, _tabs = self.build(
                    FakeExtraction(ExtractOutcome.EXTRACTED),
                    FakeSubmission(outcome),
                )
                jobs.enqueue(WORKFLOW, JobKind.SUBMIT, f"Deviation-{outcome.value}-1")
                claimed = jobs.claim("w0", ttl_s=60)
                assert claimed is not None
                self.run_job(claimed, worker, jobs)
                self.assertIs(jobs.require(claimed.id).status, JobStatus.SUCCEEDED)

    def test_submit_failure_is_not_retried(self) -> None:
        """Submission failures stay failed; a human must look."""
        self.create_item()
        worker, jobs, _auth, _tabs = self.build(
            FakeExtraction(ExtractOutcome.EXTRACTED),
            FakeSubmission(SubmitOutcome.FAILED),
        )
        jobs.enqueue(WORKFLOW, JobKind.SUBMIT, "Deviation-1-1")
        claimed = jobs.claim("w0", ttl_s=60)
        assert claimed is not None
        self.run_job(claimed, worker, jobs)
        self.assertIs(jobs.require(claimed.id).status, JobStatus.FAILED)

    def test_unknown_workflow_fails_without_crashing(self) -> None:
        """A job for an unregistered workflow fails cleanly."""
        deps = self.deps()
        jobs = JobRepository(self.db)
        events = EventRepository(self.db)
        auth = AuthGate(jobs, events)
        worker = Worker(
            "w0",
            WorkflowRegistry(),
            deps.items,
            jobs,
            events,
            auth,
            FakeTabFactory(),
        )
        job = jobs.enqueue("nope", JobKind.EXTRACT, "X")
        claimed = jobs.claim("w0", ttl_s=60)
        assert claimed is not None
        with self.assertLogs("app.jobs.worker", "ERROR"):
            self.run_job(claimed, worker, jobs)
        self.assertIs(jobs.require(job.id).status, JobStatus.FAILED)


class DispatcherTests(JobTestCase):
    """Claiming, draining and pausing."""
    def test_drains_all_queued_jobs(self) -> None:
        """All queued jobs run and each gets its own tab group."""
        for index in range(4):
            self.create_item(f"Deviation-{index}-1")
        worker, jobs, _auth, tabs = self.build(
            FakeExtraction(ExtractOutcome.EXTRACTED),
            FakeSubmission(SubmitOutcome.COMPLETED),
        )
        for index in range(4):
            jobs.enqueue(WORKFLOW, JobKind.EXTRACT, f"Deviation-{index}-1")

        async def scenario() -> None:
            dispatcher = Dispatcher(
                jobs, worker, _auth, self.settings(), poll_s=0.01
            )
            task = asyncio.create_task(dispatcher.run_forever())
            await _wait_until(
                lambda: all(
                    job.status is JobStatus.SUCCEEDED
                    for job in jobs.query(WORKFLOW)
                ),
                timeout=5.0,
            )
            dispatcher.stop()
            await task

        asyncio.run(scenario())
        self.assertEqual(len(jobs.query(WORKFLOW)), 4)
        self.assertTrue(all(job.status is JobStatus.SUCCEEDED for job in jobs.query(WORKFLOW)))
        self.assertEqual(len(tabs.groups), 4)

    def test_paused_gate_blocks_claiming(self) -> None:
        """A paused gate claims nothing until it resumes."""
        self.create_item()
        worker, jobs, auth, _tabs = self.build(
            FakeExtraction(ExtractOutcome.EXTRACTED),
            FakeSubmission(SubmitOutcome.COMPLETED),
        )
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, "Deviation-1-1")

        async def scenario() -> None:
            """Pause, assert nothing runs, resume, assert it does."""
            auth.pause("test")
            dispatcher = Dispatcher(
                jobs, worker, auth, self.settings(), poll_s=0.01
            )
            task = asyncio.create_task(dispatcher.run_forever())
            await asyncio.sleep(0.3)
            self.assertIs(jobs.query(WORKFLOW)[0].status, JobStatus.QUEUED)
            auth.resume()
            await _wait_until(
                lambda: jobs.query(WORKFLOW)[0].status is JobStatus.SUCCEEDED,
                timeout=5.0,
            )
            dispatcher.stop()
            await task

        asyncio.run(scenario())


async def _wait_until(predicate: Callable[[], bool], timeout: float) -> None:
    """Poll a predicate until it holds, then fail the test on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


if __name__ == "__main__":
    unittest.main()
