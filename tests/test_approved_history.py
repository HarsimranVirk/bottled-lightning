"""Approved-history snapshots: copy fidelity, refresh, removal and survival."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.core.list_view import ListRow
from app.core.models import PageRef, utcnow
from app.core.repo.approved_history import ApprovedHistoryRepository, HistoryQuery
from app.core.repo.attributes import AttributeRepository
from app.core.repo.decisions import DecisionRepository
from app.core.repo.edits import EditRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import DecisionKind, RefState, WorkItemStatus
from app.db.schema import SCHEMA_VERSION
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
KEY = "Deviation-1-1"


class ApprovedHistoryTests(DbTestCase):
    """The snapshot store is independent of the current work-item tables."""

    def make_item(self, key: str = KEY, ref_name: str = "Opportunity 1") -> None:
        """Create one current item with values, refs, a decision and an edit."""
        items = WorkItemRepository(self.db)
        items.create_present(
            WORKFLOW,
            ListRow(
                key=key,
                href=f"/lightning/r/a2f/{key}/view",
                columns={},
                approved_at="4/11/2026",
            ),
            utcnow(),
        )
        items.transition(WORKFLOW, key, WorkItemStatus.EXTRACTING)
        items.transition(WORKFLOW, key, WorkItemStatus.READY, extracted_at=utcnow())
        FieldValueRepository(self.db).set_extracted(
            WORKFLOW, key, {"loan_amount": "1300000", "tenure": "240"}
        )
        AttributeRepository(self.db).upsert(
            WORKFLOW, key, {"description": "Old Parameters\nLA-13,00,000"}
        )
        PageRefRepository(self.db).replace(
            WORKFLOW,
            key,
            [
                PageRef(
                    workflow=WORKFLOW,
                    item=key,
                    kind="opportunity",
                    name=ref_name,
                    url="https://example/opportunity",
                )
            ],
        )
        DecisionRepository(self.db).record(
            WORKFLOW, key, DecisionKind.ACCEPT, "looks right", utcnow()
        )
        EditRepository(self.db).record(
            WORKFLOW, key, "loan_amount", "1300000", "1450000", utcnow()
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

    def test_standard_filter_row_applies_to_the_snapshot_store(self) -> None:
        """Text, exact sets, date bounds and field filters compose with AND."""
        items = WorkItemRepository(self.db)
        fields = FieldValueRepository(self.db)
        decisions = DecisionRepository(self.db)
        history = ApprovedHistoryRepository(self.db)
        for key, status, approved_at, amount, accepted_at in (
            (
                "Deviation-A",
                WorkItemStatus.READY,
                "4/11/2026",
                "1300000",
                datetime(2026, 11, 4, tzinfo=UTC),
            ),
            (
                "Deviation-B",
                WorkItemStatus.COMPLETED,
                "5/11/2026",
                "2500000",
                datetime(2026, 9, 1, tzinfo=UTC),
            ),
        ):
            items.create_present(
                WORKFLOW,
                ListRow(
                    key=key,
                    href=f"/lightning/r/a2f/{key}/view",
                    columns={},
                    approved_at=approved_at,
                ),
                utcnow(),
            )
            conn = self.db.connect()
            conn.execute(
                "UPDATE work_items SET status = ? "
                "WHERE workflow = ? AND item_key = ?",
                [status.value, WORKFLOW, key],
            )
            conn.commit()
            fields.set_extracted(WORKFLOW, key, {"loan_amount": amount})
            decisions.record(
                WORKFLOW, key, DecisionKind.ACCEPT, None, accepted_at
            )
            history.record_accept(WORKFLOW, key, None, accepted_at)

        self.assertEqual(
            history.page(WORKFLOW, HistoryQuery(key="Deviation-A"))[1], 1
        )
        self.assertEqual(
            history.page(WORKFLOW, HistoryQuery(keys=("Deviation-B",)))[1], 1
        )
        self.assertEqual(
            history.page(WORKFLOW, HistoryQuery(status_text="comp"))[1], 1
        )
        self.assertEqual(
            history.page(WORKFLOW, HistoryQuery(statuses=("ready",)))[1], 1
        )
        self.assertEqual(
            history.page(WORKFLOW, HistoryQuery(approved_at="4/11"))[1], 1
        )
        self.assertEqual(
            history.page(
                WORKFLOW, HistoryQuery(approved_values=("5/11/2026",))
            )[1],
            1,
        )
        self.assertEqual(
            history.page(
                WORKFLOW, HistoryQuery(decided_after="2026-10-01")
            )[1],
            1,
        )
        self.assertEqual(
            history.page(
                WORKFLOW,
                HistoryQuery(field_text=(("loan_amount", "1300"),)),
            )[1],
            1,
        )
        self.assertEqual(
            history.page(
                WORKFLOW,
                HistoryQuery(field_values=(("loan_amount", "2500000"),)),
            )[1],
            1,
        )
        self.assertEqual(
            history.page(
                WORKFLOW,
                HistoryQuery(
                    statuses=("ready",),
                    field_values=(("loan_amount", "2500000"),),
                ),
            )[1],
            0,
        )

    def test_refs_for_groups_a_page_in_one_read(self) -> None:
        """The batch read returns refs per item and tolerates an empty page."""
        self.make_item()
        self.make_item("Deviation-1-2", ref_name="Opportunity 2")
        history = ApprovedHistoryRepository(self.db)
        history.record_accept(WORKFLOW, KEY, None, utcnow())
        history.record_accept(WORKFLOW, "Deviation-1-2", None, utcnow())

        grouped = history.refs_for(WORKFLOW, [KEY, "Deviation-1-2"])

        self.assertEqual(grouped[KEY]["opportunity"].name, "Opportunity 1")
        self.assertEqual(grouped["Deviation-1-2"]["opportunity"].name, "Opportunity 2")
        self.assertEqual(history.refs_for(WORKFLOW, []), {})

    def test_snapshot_keeps_ref_states_and_reasons(self) -> None:
        """A snapshot stores the missing-link state, not just the found links."""
        self.make_item()
        PageRefRepository(self.db).replace(
            WORKFLOW,
            KEY,
            [
                PageRef(
                    WORKFLOW,
                    KEY,
                    "opportunity",
                    "Opp",
                    "https://example/o",
                ),
                PageRef(
                    WORKFLOW,
                    KEY,
                    "collateral",
                    "",
                    "",
                    state=RefState.ABSENT,
                    reason="No collateral attached in Salesforce",
                ),
            ],
        )
        history = ApprovedHistoryRepository(self.db)
        history.record_accept(WORKFLOW, KEY, None, utcnow())

        snapshots = history.refs(WORKFLOW, KEY)
        self.assertIs(snapshots["opportunity"].state, RefState.FOUND)
        self.assertIs(snapshots["collateral"].state, RefState.ABSENT)
        self.assertEqual(
            snapshots["collateral"].reason, "No collateral attached in Salesforce"
        )
        grouped = history.refs_for(WORKFLOW, [KEY])
        self.assertIs(grouped[KEY]["collateral"].state, RefState.ABSENT)

    def test_ref_filters_match_kind_and_name(self) -> None:
        """Exact and contains ref filters are scoped to their object kind."""
        self.make_item()
        self.make_item("Deviation-1-2", ref_name="Opportunity 2")
        history = ApprovedHistoryRepository(self.db)
        history.record_accept(WORKFLOW, KEY, None, utcnow())
        history.record_accept(WORKFLOW, "Deviation-1-2", None, utcnow())

        exact, exact_total = history.page(
            WORKFLOW, HistoryQuery(ref_values=(("opportunity", "Opportunity 2"),))
        )
        self.assertEqual(
            ([row.key for row in exact], exact_total), (["Deviation-1-2"], 1)
        )
        self.assertEqual(
            history.page(
                WORKFLOW, HistoryQuery(ref_text=(("opportunity", "Opportunity"),))
            )[1],
            2,
        )
        self.assertEqual(
            history.page(
                WORKFLOW, HistoryQuery(ref_values=(("collateral", "Opportunity 2"),))
            )[1],
            0,
        )

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
