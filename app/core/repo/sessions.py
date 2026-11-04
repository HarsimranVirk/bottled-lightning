"""Auth snapshots and session events (FR-1.2, FR-1.5)."""

from __future__ import annotations

from datetime import datetime

from app.core.models import SessionSnapshot, from_iso, to_iso, utcnow
from app.db.connection import Database

from ._util import opt_str


class SessionRepository:
    """The persisted SF auth snapshot and session events."""

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def snapshot(self) -> SessionSnapshot | None:
        """Latest snapshot, or ``None`` when nobody has logged in."""
        row = (
            self._db.connect()
            .execute(
                "SELECT storage_state, cookie_count, created_at, org "
                "FROM sessions ORDER BY id DESC LIMIT 1"
            )
            .fetchone()
        )
        if row is None:
            return None
        created = from_iso(opt_str(row["created_at"]))
        if created is None:
            raise ValueError("missing created_at")
        return SessionSnapshot(
            storage_state=str(row["storage_state"]),
            cookie_count=int(str(row["cookie_count"])),
            created_at=created,
            org=opt_str(row["org"]),
        )

    def save(self, storage_state: str, cookie_count: int, org: str | None) -> None:
        """Persist a storage-state snapshot."""
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sessions (org, storage_state, cookie_count, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [org, storage_state, cookie_count, to_iso(utcnow())],
            )

    def clear(self) -> None:
        """Forget every saved snapshot."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM sessions")

    def event(self, event: str, detail: str = "") -> None:
        """Record an auth event."""
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO session_events (event, detail, created_at) VALUES (?, ?, ?)",
                [event, detail, to_iso(utcnow())],
            )

    def last_event(self) -> tuple[str, str, datetime] | None:
        """Most recent auth event."""
        row = (
            self._db.connect()
            .execute(
                "SELECT event, detail, created_at FROM session_events "
                "ORDER BY id DESC LIMIT 1"
            )
            .fetchone()
        )
        if row is None:
            return None
        created = from_iso(opt_str(row["created_at"]))
        if created is None:
            return None
        return str(row["event"]), opt_str(row["detail"]) or "", created
