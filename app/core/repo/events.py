"""Audit trail for item lifecycle events (FR-8.1)."""

from __future__ import annotations

from app.core.models import to_iso, utcnow
from app.db.connection import Database


class EventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def emit(
        self,
        kind: str,
        *,
        workflow: str | None = None,
        item: str | None = None,
        job_id: int | None = None,
        detail: str | None = None,
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO work_item_events (workflow, item_key, job_id, kind, detail,
                                              created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [workflow, item, job_id, kind, detail, to_iso(utcnow())],
            )

    def recent(
        self, workflow: str | None = None, item: str | None = None, limit: int = 50
    ) -> list[tuple[str, str | None, str, str | None]]:
        where: list[str] = []
        params: list[object] = []
        if workflow is not None:
            where.append("workflow = ?")
            params.append(workflow)
        if item is not None:
            where.append("item_key = ?")
            params.append(item)
        clause = "" if not where else " WHERE " + " AND ".join(where)
        rows = (
            self._db.connect()
            .execute(
                f"SELECT kind, item_key, created_at, detail FROM work_item_events{clause} "
                "ORDER BY id DESC LIMIT ?",
                [*params, limit],
            )
            .fetchall()
        )
        return [
            (
                str(row["kind"]),
                None if row["item_key"] is None else str(row["item_key"]),
                str(row["created_at"]),
                None if row["detail"] is None else str(row["detail"]),
            )
            for row in rows
        ]
