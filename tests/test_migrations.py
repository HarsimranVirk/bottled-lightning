"""Migration guard: a pre-v2 database is refused, not half-migrated."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db.connection import Database


class LegacyGuardTests(unittest.TestCase):
    """A pre-v2 database is refused rather than half-migrated."""
    def test_legacy_schema_is_refused_without_mutation(self) -> None:
        """Migration fails before creating anything next to legacy tables."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    view_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL
                );
                """
            )
            conn.commit()
            conn.close()

            database = Database(path)
            with self.assertRaises(RuntimeError):
                database.migrate()

            # Nothing was created alongside the legacy table.
            check = sqlite3.connect(path)
            names = {
                str(row[0])
                for row in check.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            check.close()
            database.close()
            self.assertEqual(names, {"jobs"})

    def test_fresh_database_migrates(self) -> None:
        """A new file gets the full v2 schema."""
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "app.db")
            database.migrate()
            names = {
                str(row[0])
                for row in database.connect()
                .execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                .fetchall()
            }
            database.close()
            self.assertIn("work_items", names)
            self.assertIn("jobs", names)


if __name__ == "__main__":
    unittest.main()
