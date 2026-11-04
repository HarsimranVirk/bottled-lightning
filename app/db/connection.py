"""Database handle: one SQLite file, one connection per thread."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .schema import SCHEMA, SCHEMA_VERSION


class _Local(threading.local):
    conn: sqlite3.Connection | None = None


class Database:
    """Owns the SQLite file and hands out per-thread connections."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._local = _Local()

    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
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
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    def migrate(self) -> None:
        conn = self.connect()
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    def close(self) -> None:
        """Close this thread's connection (tests, shutdown)."""
        conn = self._local.conn
        if conn is not None:
            conn.close()
            self._local.conn = None
