"""Repository behaviour on a migrated temp database."""

from __future__ import annotations

import unittest

from app.config import Settings, load_settings
from app.core.errors import InvalidTransition, LeaseHeld
from app.core.list_view import ListRow
from app.core.models import PageRef, SyncRun, utcnow
from app.core.repo.attributes import AttributeRepository
from app.core.repo.edits import EditRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.sync_runs import SyncRunRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import (
    ClosureSource,
    FieldStatus,
    JobKind,
    JobStatus,
    WorkItemStatus,
)
from app.db.connection import Database
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
KEY = "Deviation-28102026-484106"


def row(key: str = KEY) -> ListRow:
    return ListRow(
        key=key,
        href=f"/lightning/r/a2f/{key}/view",
        columns={},
        approved_at="2026-10-28",
    )


class WorkItemTests(DbTestCase):
    def test_lifecycle(self) -> None:
        items = WorkItemRepository(self.db)
        created = items.create_present(WORKFLOW, row(), utcnow())
        self.assertIs(created.status, WorkItemStatus.PRESENT)
        self.assertTrue(created.present)
        self.assertEqual(created.epoch, 1)
        self.assertEqual(created.approved_at, "2026-10-28")

        extracting = items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        self.assertIs(extracting.status, WorkItemStatus.EXTRACTING)

        ready = items.transition(WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow())
        self.assertIs(ready.status, WorkItemStatus.READY)
        self.assertIsNotNone(ready.extracted_at)

    def test_create_present_is_idempotent(self) -> None:
        items = WorkItemRepository(self.db)
        first = items.create_present(WORKFLOW, row(), utcnow())
        second = items.create_present(WORKFLOW, row(), utcnow())
        self.assertEqual(first, second)

    def test_illegal_transition_is_rejected(self) -> None:
        items = WorkItemRepository(self.db)
        items.create_present(WORKFLOW, row(), utcnow())
        with self.assertRaises(InvalidTransition):
            items.transition(WORKFLOW, KEY, WorkItemStatus.COMPLETED)

    def test_terminal_status_is_blocked_by_active_lease(self) -> None:
        items = WorkItemRepository(self.db)
        jobs = JobRepository(self.db)
        items.create_present(WORKFLOW, row(), utcnow())
        items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        items.transition(WORKFLOW, KEY, WorkItemStatus.READY)
        job = jobs.enqueue(WORKFLOW, JobKind.SUBMIT, KEY)
        jobs.claim("w0", ttl_s=300)

        with self.assertRaises(LeaseHeld):
            items.transition(
                WORKFLOW, KEY, WorkItemStatus.CLOSED, source=ClosureSource.EXTERNAL
            )

        # ABSENT_PENDING is not terminal, so it is allowed while leased (FR-6.11).
        pending = items.transition(WORKFLOW, KEY, WorkItemStatus.ABSENT_PENDING)
        self.assertIs(pending.status, WorkItemStatus.ABSENT_PENDING)

        jobs.complete(job.id)
        closed = items.transition(
            WORKFLOW, KEY, WorkItemStatus.CLOSED, source=ClosureSource.EXTERNAL
        )
        self.assertIs(closed.source, ClosureSource.EXTERNAL)

    def test_absent_and_new_epoch(self) -> None:
        items = WorkItemRepository(self.db)
        items.create_present(WORKFLOW, row(), utcnow())
        items.set_absent(WORKFLOW, KEY, utcnow())
        absent = items.require(WORKFLOW, KEY)
        self.assertFalse(absent.present)
        self.assertIsNotNone(absent.absent_since)

        reentered = items.begin_epoch(WORKFLOW, KEY)
        self.assertEqual(reentered.epoch, 2)
        self.assertTrue(reentered.present)
        self.assertIs(reentered.status, WorkItemStatus.PRESENT)

    def test_list_and_search(self) -> None:
        items = WorkItemRepository(self.db)
        items.create_present(WORKFLOW, row("Deviation-1-1"), utcnow())
        items.create_present(WORKFLOW, row("Deviation-2-2"), utcnow())
        items.transition(WORKFLOW, "Deviation-2-2", WorkItemStatus.EXTRACTING)

        everything, total = items.list(WORKFLOW)
        self.assertEqual(total, 2)
        self.assertEqual(len(everything), 2)

        filtered, filtered_total = items.list(
            WORKFLOW, status=WorkItemStatus.EXTRACTING
        )
        self.assertEqual(filtered_total, 1)
        self.assertEqual(filtered[0].key, "Deviation-2-2")

        found, found_total = items.list(WORKFLOW, query="Deviation-1")
        self.assertEqual(found_total, 1)
        self.assertEqual(found[0].key, "Deviation-1-1")


class FieldValueTests(DbTestCase):
    def test_proposal_survives_a_resync(self) -> None:
        fields = FieldValueRepository(self.db)
        fields.set_extracted(WORKFLOW, KEY, {"loan_amount": "2550000"})
        fields.propose(WORKFLOW, KEY, {"loan_amount": "3000000"})

        fields.set_last_synced(WORKFLOW, KEY, {"loan_amount": "2600000"})
        stored = fields.get(WORKFLOW, KEY, "loan_amount")
        assert stored is not None
        self.assertEqual(stored.proposed, "3000000")
        self.assertEqual(stored.last_synced, "2600000")
        self.assertIs(stored.status, FieldStatus.PROPOSED)

        fields.mark_applied(WORKFLOW, KEY, "loan_amount", "3000000")
        applied = fields.get(WORKFLOW, KEY, "loan_amount")
        assert applied is not None
        self.assertEqual(applied.applied, "3000000")
        self.assertIs(applied.status, FieldStatus.APPLIED)

        fields.discard_proposed(WORKFLOW, KEY)
        discarded = fields.get(WORKFLOW, KEY, "loan_amount")
        assert discarded is not None
        self.assertIsNone(discarded.proposed)
        self.assertIs(discarded.status, FieldStatus.APPLIED)

    def test_clearing_a_proposal_falls_back_to_extracted(self) -> None:
        fields = FieldValueRepository(self.db)
        fields.set_extracted(WORKFLOW, KEY, {"tenure": "240"})
        fields.propose(WORKFLOW, KEY, {"tenure": "300"})
        fields.propose(WORKFLOW, KEY, {"tenure": None})
        stored = fields.get(WORKFLOW, KEY, "tenure")
        assert stored is not None
        self.assertIsNone(stored.proposed)
        self.assertIs(stored.status, FieldStatus.EXTRACTED)


class JobTests(DbTestCase):
    def test_enqueue_dedupes_active_jobs(self) -> None:
        jobs = JobRepository(self.db)
        first = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        second = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(jobs.query(WORKFLOW)), 1)

    def test_claim_lease_and_complete(self) -> None:
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        self.assertIsNotNone(jobs.claim("w0", ttl_s=300))
        running = jobs.require(job.id)
        self.assertIs(running.status, JobStatus.RUNNING)
        self.assertEqual(running.lease_owner, "w0")
        self.assertEqual(running.attempts, 1)
        self.assertIsNone(jobs.claim("w1", ttl_s=300))

        jobs.complete(job.id)
        done = jobs.require(job.id)
        self.assertIs(done.status, JobStatus.SUCCEEDED)
        self.assertIsNone(done.lease_owner)

    def test_retryable_failure_requeues(self) -> None:
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        jobs.claim("w0", ttl_s=300)
        jobs.fail(job.id, "boom", retryable=True)
        again = jobs.require(job.id)
        self.assertIs(again.status, JobStatus.QUEUED)
        self.assertEqual(again.error, "boom")

    def test_stale_lease_is_requeued(self) -> None:
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        jobs.claim("w0", ttl_s=-1)
        self.assertEqual(jobs.requeue_stale(), 1)
        self.assertIs(jobs.require(job.id).status, JobStatus.QUEUED)

    def test_cancel_queued_job(self) -> None:
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        self.assertTrue(jobs.cancel(job.id))
        self.assertIs(jobs.require(job.id).status, JobStatus.CANCELLED)
        self.assertFalse(jobs.cancel(job.id))

    def test_logs_are_ordered(self) -> None:
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        jobs.log(job.id, "first")
        jobs.log(job.id, "second")
        self.assertEqual(jobs.logs(job.id), ["first", "second"])


class SyncRunTests(DbTestCase):
    def test_record_and_latest(self) -> None:
        runs = SyncRunRepository(self.db)
        run_id = runs.record(
            SyncRun(
                id=0,
                workflow=WORKFLOW,
                captured_at=utcnow(),
                header_total=12,
                rows_read=12,
                valid=True,
                warning=None,
                added=2,
                updated=10,
                closed=0,
            )
        )
        self.assertGreater(run_id, 0)
        latest = runs.latest(WORKFLOW)
        assert latest is not None
        self.assertEqual(latest.header_total, 12)
        self.assertTrue(latest.valid)

    def test_invalid_run_is_recorded_with_warning(self) -> None:
        runs = SyncRunRepository(self.db)
        runs.record(
            SyncRun(
                id=0,
                workflow=WORKFLOW,
                captured_at=utcnow(),
                header_total=12,
                rows_read=11,
                valid=False,
                warning="header=12 rows=11",
                added=0,
                updated=0,
                closed=0,
            )
        )
        latest = runs.latest(WORKFLOW)
        assert latest is not None
        self.assertFalse(latest.valid)
        self.assertEqual(latest.warning, "header=12 rows=11")


class SupportingRepoTests(DbTestCase):
    def test_attributes_round_trip(self) -> None:
        attrs = AttributeRepository(self.db)
        attrs.upsert(WORKFLOW, KEY, {"description": "x", "requested_roi": None})
        self.assertEqual(
            attrs.for_item(WORKFLOW, KEY),
            {"description": "x", "requested_roi": None},
        )
        attrs.upsert(WORKFLOW, KEY, {"description": "y"})
        self.assertEqual(attrs.for_item(WORKFLOW, KEY)["description"], "y")
        attrs.clear(WORKFLOW, KEY)
        self.assertEqual(attrs.for_item(WORKFLOW, KEY), {})

    def test_page_refs_replace(self) -> None:
        refs = PageRefRepository(self.db)
        refs.replace(
            WORKFLOW,
            KEY,
            [
                PageRef(WORKFLOW, KEY, "opportunity", "Opp", "https://o/1"),
                PageRef(WORKFLOW, KEY, "cl_contract", "LAI-1", "https://c/1"),
            ],
        )
        stored = refs.for_item(WORKFLOW, KEY)
        self.assertEqual(set(stored), {"opportunity", "cl_contract"})
        self.assertEqual(stored["cl_contract"].url, "https://c/1")

        refs.replace(WORKFLOW, KEY, [])
        self.assertEqual(refs.for_item(WORKFLOW, KEY), {})

    def test_edits_and_events(self) -> None:
        edits = EditRepository(self.db)
        edits.record(WORKFLOW, KEY, "loan_amount", "1", "2", utcnow())
        self.assertEqual(edits.count(WORKFLOW, KEY), 1)

        events = EventRepository(self.db)
        events.emit("extracted", workflow=WORKFLOW, item=KEY, detail="ok")
        recent = events.recent(WORKFLOW, KEY)
        self.assertEqual(recent[0][0], "extracted")

    def test_sessions_round_trip(self) -> None:
        sessions = SessionRepository(self.db)
        self.assertIsNone(sessions.snapshot())
        sessions.save('{"cookies": []}', cookie_count=0, org="hffc")
        snapshot = sessions.snapshot()
        assert snapshot is not None
        self.assertEqual(snapshot.org, "hffc")
        sessions.event("login", "manual")
        last = sessions.last_event()
        assert last is not None
        self.assertEqual(last[0], "login")
        sessions.clear()
        self.assertIsNone(sessions.snapshot())


class SettingsTests(unittest.TestCase):
    def test_list_url_is_built(self) -> None:
        settings = load_settings()
        self.assertGreaterEqual(settings.workers, 1)
        self.assertIn("Consumer_Loan_Deviation__c", settings.deviations_z02_list_url)
        self.assertIn("Z2_Loan_para_pricing1", settings.deviations_z02_list_url)
        self.assertIsInstance(settings, Settings)

    def test_migrate_creates_the_file(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "nested" / "app.db")
            database.migrate()
            self.assertTrue(database.path.exists())
            database.close()


if __name__ == "__main__":
    unittest.main()
