"""Database handle: one SQLite file, one connection per thread."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .schema import SCHEMA, SCHEMA_VERSION


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
        Create the workflow schema if needed; refuse a legacy database.

        Legacy databases (the pre-refactor ``jobs`` table has no ``kind`` column) are
        rejected before anything is created, so a migration can never half-apply to the
        wrong schema. Point ``SF_DATA_DIR`` at a new directory instead.
        """
        conn = self.connect()
        if self._is_legacy(conn):
            raise RuntimeError(
                "legacy schema detected in "
                f"{self._path} (legacy tables). This schema needs a fresh database: "
                "point SF_DATA_DIR at a new directory or delete the existing app.db "
                "(refactor plan, open item O-4)."
            )
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

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
