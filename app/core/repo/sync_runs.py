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

#: Samples kept per workflow. Matches ``recent(limit=20)``, the documented read window.
SYNC_RUNS_KEPT = 20

#: Keep the newest ``SYNC_RUNS_KEPT`` rows per workflow, delete the rest.
#:
#: ``id DESC`` is the order ``recent()`` reads, so the retained window equals the
#: readable window. The insert runs first, so the new row always has the highest id and
#: is never pruned. One statement trims every workflow, including ones no longer
#: registered. Safe to interpolate: the only value is the module constant.
_PRUNE_SQL = f"""
DELETE FROM sync_runs
 WHERE id NOT IN (
   SELECT id FROM (
     SELECT id, ROW_NUMBER() OVER (PARTITION BY workflow ORDER BY id DESC) AS rn
       FROM sync_runs
   )
   WHERE rn <= {SYNC_RUNS_KEPT}
 )
"""


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
    """
    History of list-view samples, valid and invalid, bounded per workflow.

    Invalid samples are stored with their warning rather than discarded, so a
    persistently mismatching header (the classic silent-extraction failure) is
    visible in the UI instead of looking like an empty list.

    The history is a ring: ``record`` keeps the newest :data:`SYNC_RUNS_KEPT` rows per
    workflow and prunes the rest in the insert transaction. That window matches the
    ``recent(limit=20)`` read, and the newest row (the only production reader, via
    ``latest()``) is never pruned. The prune trims every workflow at once, so rows
    belonging to a workflow that is no longer registered do not linger.
    """

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def record(self, run: SyncRun) -> int:
        """
        Append a sample result and prune the workflow's history to its newest 20 rows.

        Called by ``Reconciler.apply`` once per refresh cycle and by the dev smoke
        tools, on the browser-loop thread. The insert and the prune share one
        transaction, so once this returns no workflow holds more than
        :data:`SYNC_RUNS_KEPT` rows. Returns the new row id; raises ``LookupError`` if
        SQLite reports no id.
        """
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
            conn.execute(_PRUNE_SQL)
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
