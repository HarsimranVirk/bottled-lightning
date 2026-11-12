"""Migration guard: a pre-v2 database is refused, not half-migrated."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db.connection import Database
from app.db.schema import SCHEMA_VERSION


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


class V6MigrationTests(unittest.TestCase):
    """A v5 database gains ref states and loses the legacy ``skipped`` status."""

    def _legacy_v5(self, path: Path) -> None:
        """Build a v6 file and downgrade its shape to v5 for the migration test."""
        database = Database(path)
        database.migrate()
        conn = database.connect()
        conn.execute("ALTER TABLE work_item_refs DROP COLUMN state")
        conn.execute("ALTER TABLE work_item_refs DROP COLUMN reason")
        conn.execute("ALTER TABLE approved_deviation_refs DROP COLUMN state")
        conn.execute("ALTER TABLE approved_deviation_refs DROP COLUMN reason")
        conn.execute("PRAGMA user_version = 5")
        conn.commit()
        database.close()

    def test_v5_rows_upgrade_and_reasons_are_simplified(self) -> None:
        """Ref columns default to ``found`` and skipped rows leave the terminal state."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.db"
            self._legacy_v5(path)

            seed = sqlite3.connect(path)
            seed.execute(
                """
                INSERT INTO work_item_refs (workflow, item_key, kind, name, url)
                VALUES ('deviations_z02', 'Deviation-1-1', 'opportunity',
                        'Opp', 'https://example/o')
                """
            )
            for key, reason in (
                ("Deviation-1-2", "no record URL on the list row"),
                ("Deviation-1-3", "internal error in lms2_collateral: TimeoutError"),
            ):
                seed.execute(
                    """
                    INSERT INTO work_items
                        (workflow, item_key, status, present, epoch, first_seen,
                         last_seen, reason)
                    VALUES ('deviations_z02', ?, 'skipped', 1, 1,
                            '2026-11-01T00:00:00+00:00',
                            '2026-11-01T00:00:00+00:00', ?)
                    """,
                    [key, reason],
                )
            seed.commit()
            seed.close()

            database = Database(path)
            database.migrate()
            conn = database.connect()
            ref_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(work_item_refs)")
            }
            history_columns = {
                str(row["name"])
                for row in conn.execute(
                    "PRAGMA table_info(approved_deviation_refs)"
                )
            }
            state = conn.execute(
                "SELECT state FROM work_item_refs WHERE item_key = 'Deviation-1-1'"
            ).fetchone()
            rows = {
                str(row["item_key"]): (str(row["status"]), row["reason"])
                for row in conn.execute(
                    "SELECT item_key, status, reason FROM work_items"
                ).fetchall()
            }
            version = conn.execute("PRAGMA user_version").fetchone()
            database.close()

            self.assertIn("state", ref_columns)
            self.assertIn("reason", ref_columns)
            self.assertIn("state", history_columns)
            self.assertIn("reason", history_columns)
            self.assertEqual(str(state["state"]), "found")
            self.assertEqual(rows["Deviation-1-2"], ("present", None))
            self.assertEqual(
                rows["Deviation-1-3"],
                ("needs_review", "internal error in lms2_collateral: TimeoutError"),
            )
            self.assertEqual(int(str(version[0])), SCHEMA_VERSION)

    def test_migration_is_idempotent(self) -> None:
        """Running ``migrate`` twice changes nothing and does not fail."""
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "app.db")
            database.migrate()
            database.migrate()
            version = database.connect().execute("PRAGMA user_version").fetchone()
            database.close()
            self.assertEqual(int(str(version[0])), SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
