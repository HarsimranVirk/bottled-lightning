"""Read-only extracted attributes (description, ROI fields, product type)."""

from __future__ import annotations

from collections.abc import Mapping

from app.db.connection import Database


class AttributeRepository:
    """Read-only extracted values, keyed by name."""

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def for_item(self, workflow: str, key: str) -> dict[str, str | None]:
        """All attributes for one item."""
        rows = (
            self._db.connect()
            .execute(
                "SELECT name, value FROM work_item_attributes "
                "WHERE workflow = ? AND item_key = ? ORDER BY name",
                [workflow, key],
            )
            .fetchall()
        )
        return {
            str(row["name"]): None if row["value"] is None else str(row["value"])
            for row in rows
        }

    def upsert(self, workflow: str, key: str, values: Mapping[str, str | None]) -> None:
        """Insert or overwrite attributes for one item."""
        with self._db.transaction() as conn:
            for name, value in values.items():
                conn.execute(
                    """
                    INSERT INTO work_item_attributes (workflow, item_key, name, value)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(workflow, item_key, name) DO UPDATE SET
                        value = excluded.value
                    """,
                    [workflow, key, name, value],
                )

    def clear(self, workflow: str, key: str) -> None:
        """Drop every attribute for one item."""
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM work_item_attributes WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )
