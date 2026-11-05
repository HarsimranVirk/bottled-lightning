"""Manual retention purges: fixed cutoffs, scopes, protection and idempotency."""

from __future__ import annotations

import unittest
from datetime import timedelta

from app.core.list_view import ListRow
from app.core.models import utcnow
from app.core.repo.approved_history import ApprovedHistoryRepository
from app.core.repo.decisions import DecisionRepository
from app.core.repo.edits import EditRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import DecisionKind, JobKind, WorkItemStatus
from app.maintenance import (
    CURRENT_RETENTION_HOURS,
    HISTORY_RETENTION_DAYS,
    PurgeScope,
    PurgeService,
)
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
OLD_KEY = "Deviation-1-old"
NEW_KEY = "Deviation-1-new"


class PurgeTests(DbTestCase):
    """Both purge scopes and their safety boundaries."""

    def make_item(
        self,
        key: str,
        *,
        age: timedelta = timedelta(hours=1),
        decision: DecisionKind = DecisionKind.ACCEPT,
    ) -> None:
        """Create a current item with child rows and a backdated latest activity."""
        items = WorkItemRepository(self.db)
        at = utcnow() - age
        items.create_present(
            WORKFLOW,
            ListRow(
                key=key,
                href=f"/lightning/r/a2f/{key}/view",
                columns={},
                approved_at=None,
            ),
            at,
        )
        items.transition(WORKFLOW, key, WorkItemStatus.EXTRACTING)
        items.transition(WORKFLOW, key, WorkItemStatus.READY, extracted_at=at)
        FieldValueRepository(self.db).set_extracted(WORKFLOW, key, {"tenure": "240"})
        DecisionRepository(self.db).record(WORKFLOW, key, decision, None, at)
        EditRepository(self.db).record(WORKFLOW, key, "tenure", None, "240", at)
        EventRepository(self.db).emit(
            "extracted", workflow=WORKFLOW, item=key, detail="test"
        )
        self.db.connect().execute(
            "UPDATE work_items SET first_seen = ?, last_seen = ? "
            "WHERE workflow = ? AND item_key = ?",
            [at.isoformat(), at.isoformat(), WORKFLOW, key],
        )
        self.db.connect().commit()

    def snapshot(self, key: str, *, age: timedelta) -> None:
        """Create an approved snapshot with a chosen accept age."""
        ApprovedHistoryRepository(self.db).record_accept(
            WORKFLOW, key, None, utcnow() - age
        )

    def test_current_purge_deletes_old_item_and_children(self) -> None:
        """The current scope removes the item, its children and its decisions."""
        self.make_item(OLD_KEY, age=timedelta(hours=CURRENT_RETENTION_HOURS + 1))
        self.snapshot(OLD_KEY, age=timedelta(hours=1))
        result = PurgeService(self.db).purge(PurgeScope.CURRENT)

        self.assertEqual(result.total, 5)
        self.assertEqual(result.deleted["work_items"], 1)
        self.assertEqual(result.deleted["work_item_fields"], 1)
        self.assertEqual(result.deleted["item_decisions"], 1)
        conn = self.db.connect()
        for table in (
            "work_items",
            "work_item_fields",
            "work_item_attributes",
            "work_item_refs",
            "work_item_edits",
            "work_item_events",
            "item_decisions",
        ):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            self.assertEqual(int(str(row[0])), 0, table)
        self.assertIsNotNone(
            ApprovedHistoryRepository(self.db).get(WORKFLOW, OLD_KEY)
        )

    def test_current_purge_keeps_recent_item(self) -> None:
        """Items seen within 24 hours are untouched."""
        self.make_item(NEW_KEY, age=timedelta(hours=1))
        result = PurgeService(self.db).purge(PurgeScope.CURRENT)
        self.assertEqual(result.total, 0)
        self.assertIsNotNone(WorkItemRepository(self.db).get(WORKFLOW, NEW_KEY))

    def test_current_purge_skips_active_job(self) -> None:
        """An old item with a queued job is protected."""
        self.make_item(OLD_KEY, age=timedelta(hours=CURRENT_RETENTION_HOURS + 1))
        jobs = JobRepository(self.db)
        jobs.enqueue(WORKFLOW, JobKind.EXTRACT, OLD_KEY)
        result = PurgeService(self.db).purge(PurgeScope.CURRENT)
        self.assertEqual(result.total, 0)
        self.assertIsNotNone(WorkItemRepository(self.db).get(WORKFLOW, OLD_KEY))

    def test_dry_run_reports_without_deleting(self) -> None:
        """A dry run returns the same counts and changes nothing."""
        self.make_item(OLD_KEY, age=timedelta(hours=CURRENT_RETENTION_HOURS + 1))
        service = PurgeService(self.db)
        preview = service.purge(PurgeScope.CURRENT, dry_run=True)
        self.assertGreater(preview.total, 0)
        self.assertTrue(preview.dry_run)
        self.assertIsNotNone(WorkItemRepository(self.db).get(WORKFLOW, OLD_KEY))

        real = service.purge(PurgeScope.CURRENT)
        self.assertEqual(real.deleted, preview.deleted)

    def test_current_purge_is_idempotent(self) -> None:
        """A second run deletes zero further rows."""
        self.make_item(OLD_KEY, age=timedelta(hours=CURRENT_RETENTION_HOURS + 1))
        service = PurgeService(self.db)
        first = service.purge(PurgeScope.CURRENT)
        second = service.purge(PurgeScope.CURRENT)
        self.assertGreater(first.total, 0)
        self.assertEqual(second.total, 0)

    def test_history_purge_only_removes_old_snapshots(self) -> None:
        """The history scope keeps current data and recent snapshots."""
        self.make_item(NEW_KEY, age=timedelta(hours=1))
        ApprovedHistoryRepository(self.db).record_accept(
            WORKFLOW, NEW_KEY, None, utcnow()
        )
        self.make_item(OLD_KEY, age=timedelta(hours=1))
        ApprovedHistoryRepository(self.db).record_accept(
            WORKFLOW,
            OLD_KEY,
            None,
            utcnow() - timedelta(days=HISTORY_RETENTION_DAYS + 1),
        )

        result = PurgeService(self.db).purge(PurgeScope.HISTORY)

        self.assertEqual(result.deleted["approved_deviations"], 1)
        self.assertIsNone(ApprovedHistoryRepository(self.db).get(WORKFLOW, OLD_KEY))
        self.assertIsNotNone(ApprovedHistoryRepository(self.db).get(WORKFLOW, NEW_KEY))
        self.assertIsNotNone(WorkItemRepository(self.db).get(WORKFLOW, NEW_KEY))

    def test_purges_never_touch_sessions(self) -> None:
        """The auth snapshots are outside both scopes."""
        SessionRepository(self.db).save("{}", 1, "https://example")
        self.make_item(OLD_KEY, age=timedelta(hours=CURRENT_RETENTION_HOURS + 1))
        self.snapshot(OLD_KEY, age=timedelta(days=HISTORY_RETENTION_DAYS + 1))
        service = PurgeService(self.db)
        service.purge(PurgeScope.CURRENT)
        service.purge(PurgeScope.HISTORY)
        self.assertIsNotNone(SessionRepository(self.db).snapshot())


if __name__ == "__main__":
    unittest.main()
