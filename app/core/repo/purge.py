"""Bulk retention deletes for current work items and approved history.

This is the only place that issues destructive SQL for retention. The service above it
chooses a server-side cutoff; nothing from the API or the browser is interpolated into a
statement. Both operations use one transaction and a temporary key table so the same item
set drives the count and every child delete.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.core.models import to_iso
from app.db.connection import Database

_ACTIVE_JOB_STATUSES = ("queued", "running", "blocked_auth")

_CURRENT_CHILDREN = (
    "work_item_fields",
    "work_item_attributes",
    "work_item_refs",
    "work_item_edits",
    "work_item_events",
    "item_decisions",
)

_HISTORY_CHILDREN = (
    "approved_deviation_fields",
    "approved_deviation_attributes",
    "approved_deviation_refs",
    "approved_deviation_edits",
)


class PurgeRepository:
    """
    Execute the two manual retention scopes and return per-table deletion counts.

    ``current`` measures an item's age from ``closed_at``, ``last_seen`` or ``first_seen``
    and skips items with an active job. ``history`` measures snapshots from ``decided_at``.
    A dry run computes the same counts without deleting the real rows.

    Example:
        repo = PurgeRepository(db)
        counts = repo.current(utcnow() - timedelta(hours=24), dry_run=True)
    """

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def current(self, cutoff: datetime, dry_run: bool) -> dict[str, int]:
        """
        Delete current work items older than ``cutoff`` and their child rows.

        Items with a queued, running or blocked-auth job are protected even when their
        timestamps are old. Jobs, logs, syncs, sessions and approved history are never
        touched. Returns the count for every table considered, including zeros.
        """
        with self._db.transaction() as conn:
            self._prepare_current(conn, cutoff)
            counts = self._current_counts(conn)
            if not dry_run:
                self._delete_current(conn)
            conn.execute("DROP TABLE IF EXISTS _purge_current")
            return counts

    def history(self, cutoff: datetime, dry_run: bool) -> dict[str, int]:
        """
        Delete approved snapshots accepted before ``cutoff`` and their child rows.

        Current work items and operational tables are never touched. Returns the count
        for every snapshot table, including zeros.
        """
        with self._db.transaction() as conn:
            self._prepare_history(conn, cutoff)
            counts = self._history_counts(conn)
            if not dry_run:
                self._delete_history(conn)
            conn.execute("DROP TABLE IF EXISTS _purge_history")
            return counts

    # -- current scope -----------------------------------------------------
    def _prepare_current(self, conn: sqlite3.Connection, cutoff: datetime) -> None:
        """Build the temporary set of current items eligible for deletion."""
        placeholders = ", ".join("?" for _ in _ACTIVE_JOB_STATUSES)
        conn.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS _purge_current (
                workflow TEXT NOT NULL,
                item_key TEXT NOT NULL,
                PRIMARY KEY (workflow, item_key)
            )
            """
        )
        conn.execute("DELETE FROM _purge_current")
        conn.execute(
            f"""
            INSERT INTO _purge_current (workflow, item_key)
            SELECT w.workflow, w.item_key
              FROM work_items w
             WHERE COALESCE(w.closed_at, w.last_seen, w.first_seen) < ?
               AND NOT EXISTS (
                       SELECT 1 FROM jobs j
                        WHERE j.workflow = w.workflow
                          AND j.item_key = w.item_key
                          AND j.status IN ({placeholders})
                   )
            """,
            [to_iso(cutoff), *_ACTIVE_JOB_STATUSES],
        )

    def _current_counts(self, conn: sqlite3.Connection) -> dict[str, int]:
        """Count the current-scope rows before any delete."""
        counts: dict[str, int] = {
            "work_items": self._scalar(conn, "SELECT COUNT(*) FROM _purge_current")
        }
        for table in _CURRENT_CHILDREN:
            counts[table] = self._scalar(
                conn,
                f"""
                SELECT COUNT(*) FROM {table} t
                 WHERE EXISTS (
                           SELECT 1 FROM _purge_current p
                            WHERE p.workflow = t.workflow
                              AND p.item_key = t.item_key
                       )
                """,
            )
        return counts

    def _delete_current(self, conn: sqlite3.Connection) -> None:
        """Delete the current-scope children and then the work items."""
        for table in _CURRENT_CHILDREN:
            conn.execute(
                f"""
                DELETE FROM {table}
                 WHERE EXISTS (
                           SELECT 1 FROM _purge_current p
                            WHERE p.workflow = {table}.workflow
                              AND p.item_key = {table}.item_key
                       )
                """
            )
        conn.execute(
            """
            DELETE FROM work_items
             WHERE EXISTS (
                       SELECT 1 FROM _purge_current p
                        WHERE p.workflow = work_items.workflow
                          AND p.item_key = work_items.item_key
                   )
            """
        )

    # -- history scope -----------------------------------------------------
    def _prepare_history(self, conn: sqlite3.Connection, cutoff: datetime) -> None:
        """Build the temporary set of approved snapshots eligible for deletion."""
        conn.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS _purge_history (
                workflow TEXT NOT NULL,
                item_key TEXT NOT NULL,
                PRIMARY KEY (workflow, item_key)
            )
            """
        )
        conn.execute("DELETE FROM _purge_history")
        conn.execute(
            """
            INSERT INTO _purge_history (workflow, item_key)
            SELECT workflow, item_key
              FROM approved_deviations
             WHERE decided_at < ?
            """,
            [to_iso(cutoff)],
        )

    def _history_counts(self, conn: sqlite3.Connection) -> dict[str, int]:
        """Count the history-scope rows before any delete."""
        counts: dict[str, int] = {
            "approved_deviations": self._scalar(
                conn, "SELECT COUNT(*) FROM _purge_history"
            )
        }
        for table in _HISTORY_CHILDREN:
            counts[table] = self._scalar(
                conn,
                f"""
                SELECT COUNT(*) FROM {table} t
                 WHERE EXISTS (
                           SELECT 1 FROM _purge_history p
                            WHERE p.workflow = t.workflow
                              AND p.item_key = t.item_key
                       )
                """,
            )
        return counts

    def _delete_history(self, conn: sqlite3.Connection) -> None:
        """Delete the history-scope children and then the snapshot parents."""
        for table in _HISTORY_CHILDREN:
            conn.execute(
                f"""
                DELETE FROM {table}
                 WHERE EXISTS (
                           SELECT 1 FROM _purge_history p
                            WHERE p.workflow = {table}.workflow
                              AND p.item_key = {table}.item_key
                       )
                """
            )
        conn.execute(
            """
            DELETE FROM approved_deviations
             WHERE EXISTS (
                       SELECT 1 FROM _purge_history p
                        WHERE p.workflow = approved_deviations.workflow
                          AND p.item_key = approved_deviations.item_key
                   )
            """
        )

    @staticmethod
    def _scalar(conn: sqlite3.Connection, sql: str) -> int:
        """Run a one-column count and return an integer (zero for no row)."""
        row = conn.execute(sql).fetchone()
        return 0 if row is None else int(str(row[0]))
