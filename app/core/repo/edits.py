"""Audit of operator edits (old value → new value), written at submit time."""

from __future__ import annotations

from datetime import datetime

from app.core.models import to_iso
from app.db.connection import Database


class EditRepository:
    def __init__(self, db: Database) -> None:
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

    def count(self, workflow: str, key: str) -> int:
        row = (
            self._db.connect()
            .execute(
                "SELECT COUNT(*) FROM work_item_edits WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )
            .fetchone()
        )
        return 0 if row is None else int(str(row[0]))
