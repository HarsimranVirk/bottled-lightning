"""Repository behaviour on a migrated temp database."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.config import Settings, load_settings
from app.core.errors import InvalidTransition, LeaseHeld
from app.core.list_view import ListRow
from app.core.models import PageRef, SyncRun, utcnow
from app.core.repo.attributes import AttributeRepository
from app.core.repo.decisions import DecisionRepository
from app.core.repo.edits import EditRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.jobs import JobQuery, JobRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.sync_runs import SyncRunRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import (
    ClosureSource,
    DecisionFilter,
    DecisionKind,
    FieldStatus,
    JobKind,
    JobStatus,
    WorkItemStatus,
)
from app.db.connection import Database
from app.salesforce.urls import list_view_url
from app.workflows.deviations_z02 import LIST_FILTER, LIST_OBJECT_API
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
KEY = "Deviation-28102026-484106"


def row(key: str = KEY) -> ListRow:
    """Build a synthetic list row with a record link."""
    return ListRow(
        key=key,
        href=f"/lightning/r/a2f/{key}/view",
        columns={},
        approved_at="2026-10-28",
    )


class WorkItemTests(DbTestCase):
    """Item presence, transitions, leases and epochs."""
    def test_lifecycle(self) -> None:
        """A new item starts present and moves through extraction to ready."""
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
        """Repeated refreshes do not reset an existing item."""
        items = WorkItemRepository(self.db)
        first = items.create_present(WORKFLOW, row(), utcnow())
        second = items.create_present(WORKFLOW, row(), utcnow())
        self.assertEqual(first, second)

    def test_illegal_transition_is_rejected(self) -> None:
        """The state machine refuses jumps that skip validation."""
        items = WorkItemRepository(self.db)
        items.create_present(WORKFLOW, row(), utcnow())
        with self.assertRaises(InvalidTransition):
            items.transition(WORKFLOW, KEY, WorkItemStatus.COMPLETED)

    def test_terminal_status_is_blocked_by_active_lease(self) -> None:
        """Closing is deferred while a job runs, but absent-pending is allowed (FR-6.11)."""
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

    def test_skipped_is_allowed_under_the_jobs_own_lease(self) -> None:
        """The extraction pipeline writes SKIPPED from inside its own lease."""
        items = WorkItemRepository(self.db)
        jobs = JobRepository(self.db)
        items.create_present(WORKFLOW, row(), utcnow())
        items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        jobs.claim("w0", ttl_s=300)

        skipped = items.transition(WORKFLOW, KEY, WorkItemStatus.SKIPPED, reason="ambiguous")
        self.assertIs(skipped.status, WorkItemStatus.SKIPPED)

    def test_absent_and_new_epoch(self) -> None:
        """Absence is recorded without closing, and reappearance starts an epoch."""
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
        """Filtering, search and paging all work on the same table."""
        items = WorkItemRepository(self.db)
        items.create_present(WORKFLOW, row("Deviation-1-1"), utcnow())
        items.create_present(WORKFLOW, row("Deviation-2-2"), utcnow())
        items.transition(WORKFLOW, "Deviation-2-2", WorkItemStatus.EXTRACTING)

        everything, total = items.list(WORKFLOW)
        self.assertEqual(total, 2)
        self.assertEqual(len(everything), 2)

        filtered, filtered_total = items.list(
            WORKFLOW, statuses=[WorkItemStatus.EXTRACTING]
        )
        self.assertEqual(filtered_total, 1)
        self.assertEqual(filtered[0].key, "Deviation-2-2")

        found, found_total = items.list(WORKFLOW, query="Deviation-1")
        self.assertEqual(found_total, 1)
        self.assertEqual(found[0].key, "Deviation-1-1")


class HistoryOrderTests(DbTestCase):
    """Accepted history is ordered by the decision time, not by the last sync."""

    def test_accepted_items_sort_by_decision_time(self) -> None:
        items = WorkItemRepository(self.db)
        decisions = DecisionRepository(self.db)
        items.create_present(WORKFLOW, row("Deviation-1-1"), utcnow())
        items.create_present(WORKFLOW, row("Deviation-2-2"), utcnow())
        decisions.record(
            WORKFLOW, "Deviation-1-1", DecisionKind.ACCEPT, None,
            datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
        )
        decisions.record(
            WORKFLOW, "Deviation-2-2", DecisionKind.ACCEPT, None,
            datetime(2026, 11, 4, 11, 0, tzinfo=UTC),
        )

        newest, total = items.list(
            WORKFLOW, decision=DecisionFilter.ACCEPT, sort="decision", order="desc"
        )
        self.assertEqual(total, 2)
        self.assertEqual([item.key for item in newest], ["Deviation-2-2", "Deviation-1-1"])

        oldest, _ = items.list(
            WORKFLOW, decision=DecisionFilter.ACCEPT, sort="decision", order="asc"
        )
        self.assertEqual([item.key for item in oldest], ["Deviation-1-1", "Deviation-2-2"])


class FieldValueTests(DbTestCase):
    """Editable value precedence rules."""
    def test_proposal_survives_a_resync(self) -> None:
        """A refresh may move last_synced but never overwrites a pending edit (I4)."""
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
        """Discarding an edit restores the extracted status."""
        fields = FieldValueRepository(self.db)
        fields.set_extracted(WORKFLOW, KEY, {"tenure": "240"})
        fields.propose(WORKFLOW, KEY, {"tenure": "300"})
        fields.propose(WORKFLOW, KEY, {"tenure": None})
        stored = fields.get(WORKFLOW, KEY, "tenure")
        assert stored is not None
        self.assertIsNone(stored.proposed)
        self.assertIs(stored.status, FieldStatus.EXTRACTED)


class JobTests(DbTestCase):
    """Queue claiming, leasing and recovery."""
    def test_enqueue_dedupes_active_jobs(self) -> None:
        """The unique index prevents two active jobs for one item (I2)."""
        jobs = JobRepository(self.db)
        first = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        second = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(jobs.query(JobQuery(workflow=WORKFLOW)).jobs), 1)

    def test_claim_lease_and_complete(self) -> None:
        """A claim leases exactly one job; a second claim finds nothing."""
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
        """A retryable failure returns the job to the queue."""
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        jobs.claim("w0", ttl_s=300)
        jobs.fail(job.id, "boom", retryable=True)
        again = jobs.require(job.id)
        self.assertIs(again.status, JobStatus.QUEUED)
        self.assertEqual(again.error, "boom")

    def test_stale_lease_is_requeued(self) -> None:
        """An expired lease is recovered after a crash."""
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        jobs.claim("w0", ttl_s=-1)
        self.assertEqual(jobs.requeue_stale(), 1)
        self.assertIs(jobs.require(job.id).status, JobStatus.QUEUED)

    def test_cancel_queued_job(self) -> None:
        """Queued jobs can be cancelled once, not twice."""
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        self.assertTrue(jobs.cancel(job.id))
        self.assertIs(jobs.require(job.id).status, JobStatus.CANCELLED)
        self.assertFalse(jobs.cancel(job.id))

    def test_logs_are_ordered(self) -> None:
        """Job log sequence numbers preserve order."""
        jobs = JobRepository(self.db)
        job = jobs.enqueue(WORKFLOW, JobKind.EXTRACT, KEY)
        jobs.log(job.id, "first")
        jobs.log(job.id, "second")
        self.assertEqual(jobs.logs(job.id), ["first", "second"])


class SyncRunTests(DbTestCase):
    """Refresh history, including invalid samples."""
    def test_record_and_latest(self) -> None:
        """The latest run is returned with its counters."""
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
        """A header mismatch is stored with its warning rather than dropped."""
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

    def record_many(self, workflow: str, count: int) -> None:
        """Record ``count`` samples, numbering them in the header total."""
        runs = SyncRunRepository(self.db)
        for n in range(1, count + 1):
            runs.record(
                SyncRun(
                    id=0,
                    workflow=workflow,
                    captured_at=utcnow(),
                    header_total=n,
                    rows_read=n,
                    valid=True,
                    warning=None,
                    added=0,
                    updated=0,
                    closed=0,
                )
            )

    def test_ring_keeps_the_newest_twenty(self) -> None:
        """Recording 25 samples leaves 20, and the newest stays readable."""
        self.record_many(WORKFLOW, 25)
        row = (
            self.db.connect()
            .execute("SELECT COUNT(*) FROM sync_runs WHERE workflow = ?", [WORKFLOW])
            .fetchone()
        )
        self.assertEqual(int(str(row[0])), 20)
        latest = SyncRunRepository(self.db).latest(WORKFLOW)
        assert latest is not None
        self.assertEqual(latest.header_total, 25)
        self.assertEqual(len(SyncRunRepository(self.db).recent(WORKFLOW)), 20)

    def test_ring_is_per_workflow(self) -> None:
        """Each workflow keeps its own 20 rows; the ring trims both at once."""
        self.record_many(WORKFLOW, 25)
        self.record_many("other_workflow", 25)
        rows = (
            self.db.connect()
            .execute(
                "SELECT workflow, COUNT(*) FROM sync_runs "
                "GROUP BY workflow ORDER BY workflow"
            )
            .fetchall()
        )
        self.assertEqual(
            [(str(row[0]), int(str(row[1]))) for row in rows],
            [(WORKFLOW, 20), ("other_workflow", 20)],
        )


class SupportingRepoTests(DbTestCase):
    """Attributes, refs, edits, events and sessions."""
    def test_attributes_round_trip(self) -> None:
        """Attributes upsert by name and clear per item."""
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
        """Refs are replaced atomically, dropping stale kinds."""
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
        """Audit rows are appended and readable."""
        edits = EditRepository(self.db)
        edits.record(WORKFLOW, KEY, "loan_amount", "1", "2", utcnow())
        self.assertEqual(edits.count(WORKFLOW, KEY), 1)

        events = EventRepository(self.db)
        events.emit("extracted", workflow=WORKFLOW, item=KEY, detail="ok")
        recent = events.recent(WORKFLOW, KEY)
        self.assertEqual(recent[0][0], "extracted")

    def test_sessions_round_trip(self) -> None:
        """Snapshots save, read back, and clear."""
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
    """Settings loading and database file creation."""
    def test_settings_carry_only_global_config(self) -> None:
        """Settings has no per-workflow list URL or pattern; the workflow owns them."""
        settings = load_settings()
        self.assertGreaterEqual(settings.workers, 1)
        self.assertFalse(hasattr(settings, "deviations_z02_list_url"))
        self.assertIsInstance(settings, Settings)

    def test_list_view_url_uses_the_workflow_constants(self) -> None:
        """The Z02 list URL is built from its package constants, not Settings."""
        url = list_view_url("https://example", LIST_OBJECT_API, LIST_FILTER)
        self.assertIn("Consumer_Loan_Deviation__c", url)
        self.assertIn("Z2_Loan_para_pricing1", url)

    def test_migrate_creates_the_file(self) -> None:
        """Migration creates missing parent directories."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "nested" / "app.db")
            database.migrate()
            self.assertTrue(database.path.exists())
            database.close()


class DecisionTests(DbTestCase):
    """Append-only decisions: latest wins, undo is a pending row."""

    def test_latest_and_history(self) -> None:
        """The newest row is current; history keeps the rejected then accepted rows."""
        decisions = DecisionRepository(self.db)
        decisions.record(WORKFLOW, KEY, DecisionKind.REJECT, "bad EMI", utcnow())
        decisions.record(WORKFLOW, KEY, DecisionKind.ACCEPT, None, utcnow())

        latest = decisions.latest(WORKFLOW, KEY)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertIs(latest.decision, DecisionKind.ACCEPT)

        history = decisions.history(WORKFLOW, KEY)
        self.assertEqual(
            [row.decision for row in history],
            [DecisionKind.ACCEPT, DecisionKind.REJECT],
        )

    def test_undo_is_a_pending_row(self) -> None:
        """Undo records pending and does not delete the decision it reverses."""
        decisions = DecisionRepository(self.db)
        decisions.record(WORKFLOW, KEY, DecisionKind.ACCEPT, None, utcnow())
        decisions.record(WORKFLOW, KEY, DecisionKind.PENDING, None, utcnow())

        latest = decisions.latest(WORKFLOW, KEY)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertIs(latest.decision, DecisionKind.PENDING)
        self.assertEqual(len(decisions.history(WORKFLOW, KEY)), 2)

    def test_latest_for_skips_pending_and_other_items(self) -> None:
        """A page lookup returns only current accept/reject rows for the given keys."""
        decisions = DecisionRepository(self.db)
        decisions.record(WORKFLOW, "A", DecisionKind.ACCEPT, None, utcnow())
        decisions.record(WORKFLOW, "B", DecisionKind.REJECT, None, utcnow())
        decisions.record(WORKFLOW, "B", DecisionKind.PENDING, None, utcnow())

        current = decisions.latest_for(WORKFLOW, ["A", "B", "C"])
        self.assertEqual(set(current), {"A"})
        self.assertIs(current["A"].decision, DecisionKind.ACCEPT)

    def test_list_filters_by_decision(self) -> None:
        """The list filter reads the newest row, so undo makes an item undecided."""
        items = WorkItemRepository(self.db)
        decisions = DecisionRepository(self.db)
        items.create_present(WORKFLOW, row("A"), utcnow())
        items.create_present(WORKFLOW, row("B"), utcnow())
        decisions.record(WORKFLOW, "A", DecisionKind.ACCEPT, None, utcnow())
        decisions.record(WORKFLOW, "B", DecisionKind.REJECT, None, utcnow())

        accepted, accepted_total = items.list(
            WORKFLOW, decision=DecisionFilter.ACCEPT
        )
        self.assertEqual(accepted_total, 1)
        self.assertEqual(accepted[0].key, "A")

        undecided, undecided_total = items.list(
            WORKFLOW, decision=DecisionFilter.UNDECIDED
        )
        self.assertEqual(undecided_total, 0)

        decisions.record(WORKFLOW, "A", DecisionKind.PENDING, None, utcnow())
        undecided, undecided_total = items.list(
            WORKFLOW, decision=DecisionFilter.UNDECIDED
        )
        self.assertEqual(undecided_total, 1)
        self.assertEqual(undecided[0].key, "A")

if __name__ == "__main__":
    unittest.main()
