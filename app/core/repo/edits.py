"""Audit of operator edits (old value → new value), written at submit time."""

from __future__ import annotations

from datetime import datetime

from app.core.models import to_iso
from app.db.connection import Database


class EditRepository:
    """Audit trail of operator edits (old value to new value)."""

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def record(
        self,
        workflow: str,
        key: str,
        field_key: str,
        old_value: str | None,
        new_value: str | None,
        at: datetime,
        job_id: int | None = None,
    ) -> None:
        """Append one edit."""
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO work_item_edits
                    (workflow, item_key, field_key, old_value, new_value, job_id,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [workflow, key, field_key, old_value, new_value, job_id, to_iso(at)],
            )

    def for_item(
        self, workflow: str, key: str, limit: int = 50
    ) -> list[tuple[str, str | None, str | None, str]]:
        """Recent edits for one item as ``(field, old, new, created_at_iso)``.

        Newest first; used by the item detail endpoint so the operator can see what was
        proposed and when.
        """
        rows = (
            self._db.connect()
            .execute(
                "SELECT field_key, old_value, new_value, created_at "
                "FROM work_item_edits WHERE workflow = ? AND item_key = ? "
                "ORDER BY id DESC LIMIT ?",
                [workflow, key, limit],
            )
            .fetchall()
        )
        return [
            (
                str(row["field_key"]),
                None if row["old_value"] is None else str(row["old_value"]),
                None if row["new_value"] is None else str(row["new_value"]),
                str(row["created_at"]),
            )
            for row in rows
        ]

    def count(self, workflow: str, key: str) -> int:
        """How many edits are recorded for an item."""
        row = (
            self._db.connect()
            .execute(
                "SELECT COUNT(*) FROM work_item_edits WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )
            .fetchone()
        )
        return 0 if row is None else int(str(row[0]))
