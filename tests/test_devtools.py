"""Dev DB explorer: read-only guard, table metadata, CSV and Excel export."""

from __future__ import annotations

import io
import unittest

from openpyxl import load_workbook

from app.core.list_view import ListRow
from app.core.models import utcnow
from app.devtools.db import DevDbService, DevQueryError
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
KEY = "Deviation-03112026-486382"


class DevDbTests(DbTestCase):
    """The explorer is read-only and never exposes the session snapshot table."""

    def service(
        self, *, enabled: bool = True, allow_remote: bool = True
    ) -> DevDbService:
        """Build the service on this test's database."""
        return DevDbService(
            self.tmp_path / "test.db",
            enabled=enabled,
            allow_remote=allow_remote,
        )

    def _item(self) -> None:
        """Create one work item so the explorer has rows."""
        self.deps().items.create_present(
            WORKFLOW,
            ListRow(
                key=KEY,
                href=f"/lightning/r/a2f/{KEY}/view",
                columns={},
                approved_at=None,
            ),
            utcnow(),
        )

    def _fake_session(self) -> None:
        """Insert a token-bearing row that the explorer must never return."""
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO sessions (org, storage_state, cookie_count, created_at) "
                "VALUES (?, ?, ?, ?)",
                ["org", '{"cookies": ["sid=secret"]}', 1, utcnow().isoformat()],
            )

    def test_tables_list_every_table_except_sessions(self) -> None:
        self._item()
        self._fake_session()
        tables = {table.name: table for table in self.service().tables()}
        self.assertIn("work_items", tables)
        self.assertIn("session_events", tables)
        self.assertNotIn("sessions", tables)
        self.assertEqual(tables["work_items"].rows, 1)
        self.assertIn("item_key", tables["work_items"].columns)

    def test_select_returns_rows(self) -> None:
        self._item()
        result = self.service().query("SELECT item_key FROM work_items")
        self.assertEqual(result.columns, ("item_key",))
        self.assertEqual(result.rows, ((KEY,),))
        self.assertFalse(result.truncated)

    def test_sessions_data_is_blocked(self) -> None:
        self._fake_session()
        with self.assertRaises(DevQueryError):
            self.service().query("SELECT storage_state FROM sessions")

    def test_writes_and_pragmas_are_blocked(self) -> None:
        self._item()
        for sql in (
            "DELETE FROM work_items",
            "UPDATE work_items SET status = 'closed'",
            "CREATE TABLE nope (id INTEGER)",
            "PRAGMA table_info(work_items)",
            "ATTACH DATABASE ':memory:' AS other",
        ):
            with self.subTest(sql=sql), self.assertRaises(DevQueryError):
                self.service().query(sql)

    def test_multiple_statements_are_blocked(self) -> None:
        with self.assertRaises(DevQueryError):
            self.service().query("SELECT 1; SELECT 2")

    def test_blobs_become_placeholders(self) -> None:
        with self.db.transaction() as connection:
            connection.execute("CREATE TABLE blob_test (value BLOB)")
            connection.execute("INSERT INTO blob_test (value) VALUES (?)", [b"secret"])
        result = self.service().query("SELECT value FROM blob_test")
        self.assertEqual(result.rows, (("<blob 6 bytes>",),))

    def test_csv_export(self) -> None:
        self._item()
        content = self.service().export_csv("SELECT item_key FROM work_items")
        self.assertIn("item_key", content)
        self.assertIn(KEY, content)

    def test_excel_export_is_a_real_workbook(self) -> None:
        self._item()
        content = self.service().export_xlsx("SELECT item_key FROM work_items")
        workbook = load_workbook(io.BytesIO(content))
        sheet = workbook["Query"]
        self.assertEqual(sheet.cell(row=1, column=1).value, "item_key")
        self.assertEqual(sheet.cell(row=2, column=1).value, KEY)

    def test_export_limit_is_enforced(self) -> None:
        self._item()
        self.deps().items.create_present(
            WORKFLOW,
            ListRow(
                key="Deviation-03112026-000000",
                href="/lightning/r/a2f/other/view",
                columns={},
                approved_at=None,
            ),
            utcnow(),
        )
        with self.assertRaises(DevQueryError):
            self.service().export_csv("SELECT item_key FROM work_items", limit=1)

    def test_disabled_and_remote_are_rejected(self) -> None:
        disabled = self.service(enabled=False)
        with self.assertRaises(DevQueryError):
            disabled.require_allowed("127.0.0.1")
        local_only = self.service(allow_remote=False)
        with self.assertRaises(DevQueryError):
            local_only.require_allowed("10.0.0.5")
        local_only.require_allowed("127.0.0.1")


if __name__ == "__main__":
    unittest.main()
