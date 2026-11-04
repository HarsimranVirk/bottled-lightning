"""Typed links from an item to the SF objects involved in it."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.models import PageRef
from app.db.connection import Database


class PageRefRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def for_item(self, workflow: str, key: str) -> dict[str, PageRef]:
        rows = (
            self._db.connect()
            .execute(
                "SELECT kind, name, url FROM work_item_refs "
                "WHERE workflow = ? AND item_key = ? ORDER BY kind",
                [workflow, key],
            )
            .fetchall()
        )
        return {
            str(row["kind"]): PageRef(
                workflow=workflow,
                item=key,
                kind=str(row["kind"]),
                name=str(row["name"]),
                url=str(row["url"]),
            )
            for row in rows
        }

    def replace(self, workflow: str, key: str, refs: Sequence[PageRef]) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM work_item_refs WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )
            for ref in refs:
                conn.execute(
                    """
                    INSERT INTO work_item_refs (workflow, item_key, kind, name, url)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [workflow, key, ref.kind, ref.name, ref.url],
                )
