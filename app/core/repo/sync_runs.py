"""Refresh history: one row per list-view sample (FR-2.4, FR-2.9)."""

from __future__ import annotations

import sqlite3

from app.core.models import SyncRun, from_iso, to_iso
from app.db.connection import Database

from ._util import opt_int, opt_str

_COLUMNS = (
    "id, workflow, captured_at, header_total, rows_read, valid, warning, added, "
    "updated, closed"
)


def _to_run(row: sqlite3.Row) -> SyncRun:
    """Map a row to a ``SyncRun``."""
    captured = from_iso(opt_str(row["captured_at"]))
    if captured is None:
        raise ValueError("missing captured_at")
    return SyncRun(
        id=int(str(row["id"])),
        workflow=str(row["workflow"]),
        captured_at=captured,
        header_total=opt_int(row["header_total"]),
        rows_read=int(str(row["rows_read"])),
        valid=bool(row["valid"]),
        warning=opt_str(row["warning"]),
        added=int(str(row["added"])),
        updated=int(str(row["updated"])),
        closed=int(str(row["closed"])),
    )


class SyncRunRepository:
    """History of list-view samples, valid and invalid."""

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def record(self, run: SyncRun) -> int:
        """Append a sample result; returns its id."""
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sync_runs
                    (workflow, captured_at, header_total, rows_read, valid, warning,
                     added, updated, closed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run.workflow,
                    to_iso(run.captured_at),
                    run.header_total,
                    run.rows_read,
                    1 if run.valid else 0,
                    run.warning,
                    run.added,
                    run.updated,
                    run.closed,
                ],
            )
            run_id = cursor.lastrowid
        if run_id is None:
            raise LookupError("sync run insert returned no id")
        return int(run_id)

    def latest(self, workflow: str) -> SyncRun | None:
        """Most recent sample for a workflow."""
        row = (
            self._db.connect()
            .execute(
                f"SELECT {_COLUMNS} FROM sync_runs WHERE workflow = ? "
                "ORDER BY id DESC LIMIT 1",
                [workflow],
            )
            .fetchone()
        )
        return None if row is None else _to_run(row)

    def recent(self, workflow: str, limit: int = 20) -> list[SyncRun]:
        """The last ``limit`` samples for a workflow."""
        rows = (
            self._db.connect()
            .execute(
                f"SELECT {_COLUMNS} FROM sync_runs WHERE workflow = ? "
                "ORDER BY id DESC LIMIT ?",
                [workflow, limit],
            )
            .fetchall()
        )
        return [_to_run(row) for row in rows]
