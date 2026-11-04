"""Editable field values: extracted / last synced / proposed / applied."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from app.core.models import FieldValue, to_iso, utcnow
from app.core.status import FieldStatus
from app.db.connection import Database

from ._util import opt_str, opt_time

_COLUMNS = (
    "workflow, item_key, field_key, extracted, last_synced, proposed, applied, "
    "status, updated_at"
)

_UPSERT = """
INSERT INTO work_item_fields
    (workflow, item_key, field_key, extracted, last_synced, proposed, applied, status,
     updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(workflow, item_key, field_key) DO UPDATE SET
    extracted = excluded.extracted,
    last_synced = excluded.last_synced,
    proposed = excluded.proposed,
    applied = excluded.applied,
    status = excluded.status,
    updated_at = excluded.updated_at
"""


def _to_field(row: sqlite3.Row) -> FieldValue:
    updated = opt_time(row["updated_at"])
    if updated is None:
        raise ValueError("missing updated_at")
    return FieldValue(
        workflow=str(row["workflow"]),
        item=str(row["item_key"]),
        key=str(row["field_key"]),
        extracted=opt_str(row["extracted"]),
        last_synced=opt_str(row["last_synced"]),
        proposed=opt_str(row["proposed"]),
        applied=opt_str(row["applied"]),
        status=FieldStatus(str(row["status"])),
        updated_at=updated,
    )


class FieldValueRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def for_item(self, workflow: str, key: str) -> dict[str, FieldValue]:
        rows = (
            self._db.connect()
            .execute(
                f"SELECT {_COLUMNS} FROM work_item_fields "
                "WHERE workflow = ? AND item_key = ? ORDER BY field_key",
                [workflow, key],
            )
            .fetchall()
        )
        return {str(row["field_key"]): _to_field(row) for row in rows}

    def get(self, workflow: str, key: str, field_key: str) -> FieldValue | None:
        row = (
            self._db.connect()
            .execute(
                f"SELECT {_COLUMNS} FROM work_item_fields "
                "WHERE workflow = ? AND item_key = ? AND field_key = ?",
                [workflow, key, field_key],
            )
            .fetchone()
        )
        return None if row is None else _to_field(row)

    def set_extracted(
        self, workflow: str, key: str, values: Mapping[str, str | None]
    ) -> None:
        """Seed scraped values. Never disturbs a pending proposal (FR-2.5 / I4)."""
        stamp = to_iso(utcnow())
        with self._db.transaction() as conn:
            for field_key, value in values.items():
                conn.execute(
                    """
                    INSERT INTO work_item_fields
                        (workflow, item_key, field_key, extracted, last_synced, proposed,
                         applied, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                    ON CONFLICT(workflow, item_key, field_key) DO UPDATE SET
                        extracted = excluded.extracted,
                        last_synced = COALESCE(
                            work_item_fields.last_synced, excluded.extracted
                        ),
                        status = CASE
                            WHEN work_item_fields.proposed IS NULL
                            THEN excluded.status
                            ELSE work_item_fields.status
                        END,
                        updated_at = excluded.updated_at
                    """,
                    [
                        workflow,
                        key,
                        field_key,
                        value,
                        value,
                        FieldStatus.EXTRACTED.value,
                        stamp,
                    ],
                )

    def set_last_synced(
        self, workflow: str, key: str, values: Mapping[str, str | None]
    ) -> None:
        """Update the SF-observed value only; the operator's proposal wins."""
        stamp = to_iso(utcnow())
        with self._db.transaction() as conn:
            for field_key, value in values.items():
                conn.execute(
                    """
                    INSERT INTO work_item_fields
                        (workflow, item_key, field_key, extracted, last_synced, proposed,
                         applied, status, updated_at)
                    VALUES (?, ?, ?, NULL, ?, NULL, NULL, ?, ?)
                    ON CONFLICT(workflow, item_key, field_key) DO UPDATE SET
                        last_synced = excluded.last_synced,
                        updated_at = excluded.updated_at
                    """,
                    [
                        workflow,
                        key,
                        field_key,
                        value,
                        FieldStatus.EXTRACTED.value,
                        stamp,
                    ],
                )

    def propose(
        self, workflow: str, key: str, changes: Mapping[str, str | None]
    ) -> None:
        """Set or clear a proposed value. ``None`` clears it and falls back to extracted."""
        stamp = to_iso(utcnow())
        with self._db.transaction() as conn:
            for field_key, value in changes.items():
                if value is None:
                    conn.execute(
                        """
                        UPDATE work_item_fields
                           SET proposed = NULL,
                               status = CASE
                                   WHEN applied IS NOT NULL THEN ?
                                   ELSE ?
                               END,
                               updated_at = ?
                         WHERE workflow = ? AND item_key = ? AND field_key = ?
                        """,
                        [
                            FieldStatus.APPLIED.value,
                            FieldStatus.EXTRACTED.value,
                            stamp,
                            workflow,
                            key,
                            field_key,
                        ],
                    )
                    continue
                conn.execute(
                    """
                    INSERT INTO work_item_fields
                        (workflow, item_key, field_key, extracted, last_synced, proposed,
                         applied, status, updated_at)
                    VALUES (?, ?, ?, NULL, NULL, ?, NULL, ?, ?)
                    ON CONFLICT(workflow, item_key, field_key) DO UPDATE SET
                        proposed = excluded.proposed,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    [
                        workflow,
                        key,
                        field_key,
                        value,
                        FieldStatus.PROPOSED.value,
                        stamp,
                    ],
                )

    def discard_proposed(self, workflow: str, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE work_item_fields
                   SET proposed = NULL,
                       status = CASE
                           WHEN applied IS NOT NULL THEN ?
                           ELSE ?
                       END,
                       updated_at = ?
                 WHERE workflow = ? AND item_key = ?
                """,
                [
                    FieldStatus.APPLIED.value,
                    FieldStatus.EXTRACTED.value,
                    to_iso(utcnow()),
                    workflow,
                    key,
                ],
            )

    def mark_applied(self, workflow: str, key: str, field_key: str, value: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE work_item_fields
                   SET applied = ?, status = ?, updated_at = ?
                 WHERE workflow = ? AND item_key = ? AND field_key = ?
                """,
                [
                    value,
                    FieldStatus.APPLIED.value,
                    to_iso(utcnow()),
                    workflow,
                    key,
                    field_key,
                ],
            )

    def mark_rejected(self, workflow: str, key: str, field_key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE work_item_fields
                   SET status = ?, updated_at = ?
                 WHERE workflow = ? AND item_key = ? AND field_key = ?
                """,
                [FieldStatus.REJECTED.value, to_iso(utcnow()), workflow, key, field_key],
            )
