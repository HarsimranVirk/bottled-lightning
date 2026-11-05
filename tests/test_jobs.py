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
from app.core.repo.jobs import JobQuery, JobRepository
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
from app.pipeline.closure import ClosureResolver
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
        closure = ClosureResolver(deps.items, jobs, events)
        worker = Worker(
            name,
            registry,
            deps.items,
            jobs,
            events,
            auth,
            tabs,
            closure,
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
            ClosureResolver(deps.items, jobs, events),
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
                    for job in jobs.query(JobQuery(workflow=WORKFLOW)).jobs
                ),
                timeout=5.0,
            )
            dispatcher.stop()
            await task

        asyncio.run(scenario())
        self.assertEqual(len(jobs.query(JobQuery(workflow=WORKFLOW)).jobs), 4)
        self.assertTrue(all(job.status is JobStatus.SUCCEEDED for job in jobs.query(JobQuery(workflow=WORKFLOW)).jobs))
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
            self.assertIs(jobs.query(JobQuery(workflow=WORKFLOW)).jobs[0].status, JobStatus.QUEUED)
            auth.resume()
            await _wait_until(
                lambda: jobs.query(JobQuery(workflow=WORKFLOW)).jobs[0].status is JobStatus.SUCCEEDED,
                timeout=5.0,
            )
            dispatcher.stop()
            await task

        asyncio.run(scenario())


class JobQueryTests(DbTestCase):
    """Filtering, sorting and pagination for the jobs table (FR-7.10)."""

    def seed(self) -> dict[str, Job]:
        """Three jobs with controlled timestamps, phases and errors."""
        jobs = JobRepository(self.db)
        rows = [
            ("Deviation-1-1", JobKind.EXTRACT, "2026-11-04T10:00:00+00:00",
             "2026-11-04T10:00:10+00:00", Phase.EXTRACT, None, JobStatus.SUCCEEDED),
            ("Deviation-2-2", JobKind.EXTRACT, "2026-11-04T10:01:00+00:00",
             "2026-11-04T10:01:30+00:00", Phase.EXTRACT, "boom", JobStatus.FAILED),
            ("Deviation-3-3", JobKind.SUBMIT, "2026-11-04T10:02:00+00:00",
             "2026-11-04T10:02:05+00:00", Phase.APPLY, None, JobStatus.SUCCEEDED),
        ]
        seeded: dict[str, Job] = {}
        for key, kind, started, finished, phase, error, status in rows:
            job = jobs.enqueue(WORKFLOW, kind, key)
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE jobs SET started_at = ?, finished_at = ?, phase = ?, "
                    "error = ?, status = ? WHERE id = ?",
                    [started, finished, phase.value, error, status.value, job.id],
                )
            seeded[key] = jobs.require(job.id)
        return seeded

    def test_each_filter_and_composition(self) -> None:
        """Every column filter works, and filters compose with AND."""
        self.seed()
        jobs = JobRepository(self.db)

        self.assertEqual(len(jobs.query(JobQuery(kind=JobKind.EXTRACT)).jobs), 2)
        self.assertEqual(len(jobs.query(JobQuery(status=JobStatus.FAILED)).jobs), 1)
        failed = jobs.query(JobQuery(kind=JobKind.EXTRACT, status=JobStatus.FAILED)).jobs
        self.assertEqual([job.item for job in failed], ["Deviation-2-2"])

        self.assertEqual(
            [job.item for job in jobs.query(JobQuery(phase=Phase.APPLY)).jobs],
            ["Deviation-3-3"],
        )
        self.assertEqual(
            [job.item for job in jobs.query(JobQuery(item="2-2")).jobs],
            ["Deviation-2-2"],
        )
        self.assertEqual(len(jobs.query(JobQuery(error="boo")).jobs), 1)
        job_id = jobs.query(JobQuery(item="3-3")).jobs[0].id
        self.assertEqual(len(jobs.query(JobQuery(job_id=str(job_id))).jobs), 1)

    def test_multiselect_and_exact_value_filters(self) -> None:
        """The standard table filter sends OR'd exact sets and text contains filters."""
        seeded = self.seed()
        jobs = JobRepository(self.db)

        self.assertEqual(
            jobs.query(
                JobQuery(statuses=(JobStatus.FAILED, JobStatus.SUCCEEDED))
            ).total,
            3,
        )
        self.assertEqual(jobs.query(JobQuery(kinds=(JobKind.SUBMIT,))).total, 1)
        self.assertEqual(jobs.query(JobQuery(phases=(Phase.APPLY,))).total, 1)
        self.assertEqual(jobs.query(JobQuery(status_text="fail")).total, 1)
        self.assertEqual(jobs.query(JobQuery(kind_text="ext")).total, 2)
        self.assertEqual(jobs.query(JobQuery(phase_text="app")).total, 1)
        self.assertEqual(
            jobs.query(
                JobQuery(job_ids_in=(str(seeded["Deviation-3-3"].id),))
            ).total,
            1,
        )
        self.assertEqual(
            jobs.query(
                JobQuery(items_in=("Deviation-1-1", "Deviation-3-3"))
            ).total,
            2,
        )
        self.assertEqual(jobs.query(JobQuery(errors_in=("boom",))).total, 1)
        self.assertEqual(
            jobs.query(
                JobQuery(
                    kinds=(JobKind.EXTRACT,),
                    statuses=(JobStatus.FAILED,),
                )
            ).total,
            1,
        )

    def test_started_date_and_duration_ranges(self) -> None:
        """Date bounds are inclusive UTC days and duration bounds are milliseconds."""
        self.seed()
        jobs = JobRepository(self.db)
        self.assertEqual(
            len(jobs.query(JobQuery(started_after="2026-11-04", started_before="2026-11-04")).jobs),
            3,
        )
        self.assertEqual(
            len(jobs.query(JobQuery(started_after="2026-11-05")).jobs), 0
        )
        slow = jobs.query(JobQuery(duration_min_ms=20_000, duration_max_ms=40_000)).jobs
        self.assertEqual([job.item for job in slow], ["Deviation-2-2"])

    def test_pagination_total_and_sort(self) -> None:
        """The total counts the filtered set; order and paging are server-side."""
        self.seed()
        jobs = JobRepository(self.db)
        first = jobs.query(JobQuery(limit=2, offset=0))
        self.assertEqual(first.total, 3)
        self.assertEqual([job.item for job in first.jobs], ["Deviation-3-3", "Deviation-2-2"])

        second = jobs.query(JobQuery(limit=2, offset=2))
        self.assertEqual([job.item for job in second.jobs], ["Deviation-1-1"])

        fastest = jobs.query(JobQuery(sort="duration", order="asc")).jobs
        self.assertEqual([job.item for job in fastest], ["Deviation-3-3", "Deviation-1-1", "Deviation-2-2"])

    def test_nulls_sort_last(self) -> None:
        """A queued job has no duration and sorts after every started job."""
        self.seed()
        jobs = JobRepository(self.db)
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, "Deviation-4-4")
        ordered = jobs.query(JobQuery(sort="duration", order="desc")).jobs
        self.assertEqual(ordered[-1].item, "Deviation-4-4")

    def test_unknown_sort_is_a_validation_error(self) -> None:
        """The sort key is a whitelist, not SQL passthrough."""
        jobs = JobRepository(self.db)
        with self.assertRaises(ValueError):
            jobs.query(JobQuery(sort="drop table"))
        with self.assertRaises(ValueError):
            jobs.query(JobQuery(order="sideways"))


class DurationTests(unittest.TestCase):
    """Duration is derived from the stored timestamps."""

    def test_duration_cases(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.core.models import job_duration_ms

        started = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
        job = Job(
            id=1, workflow=WORKFLOW, kind=JobKind.EXTRACT, item="Deviation-1-1",
            status=JobStatus.RUNNING, phase=None, attempts=1, lease_owner="w0",
            lease_expires_at=None, created_at=started, started_at=started,
            finished_at=None, error=None,
        )
        self.assertEqual(job_duration_ms(job, started + timedelta(seconds=3)), 3000)
        self.assertIsNone(
            job_duration_ms(
                Job(
                    id=2, workflow=WORKFLOW, kind=JobKind.EXTRACT, item="Deviation-2-2",
                    status=JobStatus.QUEUED, phase=None, attempts=0, lease_owner=None,
                    lease_expires_at=None, created_at=started, started_at=None,
                    finished_at=None, error=None,
                ),
                started,
            )
        )



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
