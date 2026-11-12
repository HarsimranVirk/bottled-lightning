"""Database handle: one SQLite file, one connection per thread."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .schema import (
    BACKFILL_APPROVED_HISTORY,
    BACKFILL_V6_STATUSES,
    SCHEMA,
    SCHEMA_VERSION,
    V6_ADDED_COLUMNS,
)


class _Local(threading.local):
    """Thread-local storage for this thread's connection."""

    conn: sqlite3.Connection | None = None


class Database:
    """
    One SQLite file with one connection per thread.

    Repositories take this handle; nothing else opens a connection. WAL mode keeps
    the watcher, the job loop and request handlers from blocking each other, and
    ``foreign_keys`` is on so cascades behave.

    Example:
        db = Database(settings.db_path)
        db.migrate()
        items = WorkItemRepository(db)
    """

    def __init__(self, path: Path) -> None:
        """Point the handle at ``path``; connections are opened lazily."""
        self._path = path
        self._local = _Local()

    @property
    def path(self) -> Path:
        """Path of the SQLite file."""
        return self._path

    def connect(self) -> sqlite3.Connection:
        """
        Return this thread's connection, opening and configuring it once.

        Configuration applied on first use: WAL journal, ``foreign_keys`` and a 5s busy
        timeout. The connection is cached per thread, so a thread must not be shared
        between unrelated callers without care.
        """
        conn = self._local.conn
        if conn is not None:
            return conn
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        self._local.conn = conn
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Run a unit of work; commit on success, roll back on any exception.

        Example:
            with db.transaction() as conn:
                conn.execute("INSERT ...")
                conn.execute("UPDATE ...")
        """
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    def migrate(self) -> None:
        """
        Create or upgrade the workflow schema; refuse a legacy database.

        Legacy databases (the pre-refactor ``jobs`` table has no ``kind`` column) are
        rejected before anything is created, so a migration can never half-apply to the
        wrong schema. Point ``SF_DATA_DIR`` at a new directory instead.

        A database older than version 5 receives the approved-history tables and a
        one-time backfill of every current item whose latest decision is ``accept``.
        A database older than version 6 gains the ref ``state``/``reason`` columns and
        the one-time ``skipped`` -> ``needs_review`` status migration. The backfills and
        the ``user_version`` bump commit together, so a crash retries the copy instead of
        skipping it.
        """
        conn = self.connect()
        if self._is_legacy(conn):
            raise RuntimeError(
                "legacy schema detected in "
                f"{self._path} (legacy tables). This schema needs a fresh database: "
                "point SF_DATA_DIR at a new directory or delete the existing app.db "
                "(refactor plan, open item O-4)."
            )
        version_row = conn.execute("PRAGMA user_version").fetchone()
        version = int(str(version_row[0])) if version_row is not None else 0
        conn.executescript(SCHEMA)
        try:
            if version < 5:
                # ``executescript`` committed the additive DDL; the backfill and the
                # version bump commit together so a crash retries the copy instead of
                # skipping it.
                for statement in BACKFILL_APPROVED_HISTORY:
                    conn.execute(statement)
            self._add_missing_columns(conn)
            if version < 6:
                for statement in BACKFILL_V6_STATUSES:
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    def _add_missing_columns(self, conn: sqlite3.Connection) -> None:
        """Add the v6 ref columns to a table created before this schema version.

        ``CREATE TABLE IF NOT EXISTS`` is a no-op on an existing table, so an upgraded
        database needs explicit ``ALTER TABLE``. Checking ``PRAGMA table_info`` first
        keeps the step idempotent across a crash and harmless on a fresh database.
        """
        for table, column, declaration in V6_ADDED_COLUMNS:
            columns = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _is_legacy(self, conn: sqlite3.Connection) -> bool:
        """True when the file holds the pre-refactor schema (its ``jobs`` table has no
        ``kind`` column). Detected before creating anything so a legacy DB is untouched."""
        rows = conn.execute("PRAGMA table_info(jobs)").fetchall()
        if not rows:
            return False
        columns = {str(row["name"]) for row in rows}
        return "kind" not in columns

    def close(self) -> None:
        """Close this thread's connection (tests and shutdown)."""
        conn = self._local.conn
        if conn is not None:
            conn.close()
            self._local.conn = None
