"""Approved-history snapshots: copy fidelity, refresh, removal and survival."""

from __future__ import annotations

import unittest
from datetime import timedelta

from app.core.list_view import ListRow
from app.core.models import PageRef, utcnow
from app.core.repo.approved_history import ApprovedHistoryRepository
from app.core.repo.attributes import AttributeRepository
from app.core.repo.decisions import DecisionRepository
from app.core.repo.edits import EditRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import DecisionKind, WorkItemStatus
from app.db.schema import SCHEMA_VERSION
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
KEY = "Deviation-1-1"


class ApprovedHistoryTests(DbTestCase):
    """The snapshot store is independent of the current work-item tables."""

    def make_item(self) -> None:
        """Create one current item with values, refs, a decision and an edit."""
        items = WorkItemRepository(self.db)
        items.create_present(
            WORKFLOW,
            ListRow(
                key=KEY,
                href=f"/lightning/r/a2f/{KEY}/view",
                columns={},
                approved_at="4/11/2026",
            ),
            utcnow(),
        )
        items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        items.transition(WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow())
        FieldValueRepository(self.db).set_extracted(
            WORKFLOW, KEY, {"loan_amount": "1300000", "tenure": "240"}
        )
        AttributeRepository(self.db).upsert(
            WORKFLOW, KEY, {"description": "Old Parameters\nLA-13,00,000"}
        )
        PageRefRepository(self.db).replace(
            WORKFLOW,
            KEY,
            [
                PageRef(
                    workflow=WORKFLOW,
                    item=KEY,
                    kind="opportunity",
                    name="Opportunity 1",
                    url="https://example/opportunity",
                )
            ],
        )
        DecisionRepository(self.db).record(
            WORKFLOW, KEY, DecisionKind.ACCEPT, "looks right", utcnow()
        )
        EditRepository(self.db).record(
            WORKFLOW, KEY, "loan_amount", "1300000", "1450000", utcnow()
        )

    def test_record_accept_copies_parent_and_children(self) -> None:
        """The snapshot contains every value the history detail needs."""
        self.make_item()
        history = ApprovedHistoryRepository(self.db)
        history.record_accept(WORKFLOW, KEY, "looks right", utcnow())

        approved = history.get(WORKFLOW, KEY)
        assert approved is not None
        self.assertEqual(approved.key, KEY)
        self.assertEqual(approved.status, WorkItemStatus.READY)
        self.assertEqual(approved.approved_at, "4/11/2026")
        self.assertEqual(approved.decision_reason, "looks right")
        self.assertEqual(history.fields(WORKFLOW, KEY)["loan_amount"].extracted, "1300000")
        self.assertEqual(
            history.attributes(WORKFLOW, KEY)["description"],
            "Old Parameters\nLA-13,00,000",
        )
        self.assertEqual(history.refs(WORKFLOW, KEY)["opportunity"].name, "Opportunity 1")
        self.assertEqual(len(history.edits(WORKFLOW, KEY)), 1)

    def test_refresh_updates_status_and_children(self) -> None:
        """A submit/closure refresh changes observed state but not the accept time."""
        self.make_item()
        history = ApprovedHistoryRepository(self.db)
        accepted_at = utcnow() - timedelta(hours=1)
        history.record_accept(WORKFLOW, KEY, "looks right", accepted_at)

        conn = self.db.connect()
        conn.execute(
            "UPDATE work_items SET status = ? WHERE workflow = ? AND item_key = ?",
            [WorkItemStatus.COMPLETED.value, WORKFLOW, KEY],
        )
        conn.commit()
        FieldValueRepository(self.db).mark_applied(
            WORKFLOW, KEY, "loan_amount", "1450000"
        )
        history.refresh(WORKFLOW, KEY)

        approved = history.get(WORKFLOW, KEY)
        assert approved is not None
        self.assertEqual(approved.status, WorkItemStatus.COMPLETED)
        self.assertEqual(approved.decided_at, accepted_at)
        self.assertEqual(history.fields(WORKFLOW, KEY)["loan_amount"].applied, "1450000")

    def test_remove_cascades_every_child(self) -> None:
        """Undo/reject removes the parent and all snapshot children."""
        self.make_item()
        history = ApprovedHistoryRepository(self.db)
        history.record_accept(WORKFLOW, KEY, None, utcnow())
        history.remove(WORKFLOW, KEY)

        self.assertIsNone(history.get(WORKFLOW, KEY))
        conn = self.db.connect()
        for table in (
            "approved_deviation_fields",
            "approved_deviation_attributes",
            "approved_deviation_refs",
            "approved_deviation_edits",
        ):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            self.assertEqual(int(str(row[0])), 0, table)

    def test_snapshot_survives_current_item_deletion(self) -> None:
        """Deleting the current item and its children cannot blank the snapshot."""
        self.make_item()
        history = ApprovedHistoryRepository(self.db)
        history.record_accept(WORKFLOW, KEY, None, utcnow())

        conn = self.db.connect()
        for table in (
            "work_item_fields",
            "work_item_attributes",
            "work_item_refs",
            "work_item_edits",
            "work_item_events",
            "item_decisions",
            "work_items",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

        approved = history.get(WORKFLOW, KEY)
        assert approved is not None
        self.assertEqual(approved.key, KEY)
        self.assertEqual(history.fields(WORKFLOW, KEY)["loan_amount"].extracted, "1300000")

    def test_v4_to_v5_backfill_copies_accepted_items(self) -> None:
        """An existing accepted item is backfilled once on the schema upgrade."""
        self.make_item()
        conn = self.db.connect()
        conn.execute("PRAGMA user_version = 4")
        conn.commit()

        self.db.migrate()

        history = ApprovedHistoryRepository(self.db)
        approved = history.get(WORKFLOW, KEY)
        assert approved is not None
        self.assertEqual(approved.decision_reason, "looks right")
        self.assertEqual(len(history.edits(WORKFLOW, KEY)), 1)
        version = conn.execute("PRAGMA user_version").fetchone()
        self.assertEqual(int(str(version[0])), SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
