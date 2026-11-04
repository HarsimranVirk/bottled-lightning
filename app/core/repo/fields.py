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
    """Map a row to a ``FieldValue``."""
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
    """
    Editable value state: extracted, synced, proposed, applied.

    The repository enforces the precedence rule that makes resync safe: a refresh
    may move ``last_synced`` but never touches ``proposed``, so an operator's
    pending edit survives the next 30-second cycle (FR-2.5 / invariant I4).
    """

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def for_item(self, workflow: str, key: str) -> dict[str, FieldValue]:
        """All editable values for one item."""
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
        """One editable value, or ``None``."""
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
        """
        Seed scraped values; never disturbs a pending proposal.

        Writes ``extracted`` (and ``last_synced`` if it was null). If the operator has
        already proposed a value, the row's status is left alone.

        Example:
            fields.set_extracted(workflow, key, {"loan_amount": "25,50,000"})
        """
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
        """
        Update the SF-observed value only; the operator's proposal wins.

        Example (operator is mid-edit, SF value changed underneath):
            fields.propose(workflow, key, {"tenure": "300"})
            fields.set_last_synced(workflow, key, {"tenure": "240"})
            # proposed=300, last_synced=240, status=PROPOSED
        """
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
        """
        Set or clear a proposed value.

        ``None`` clears the proposal and falls back to ``APPLIED`` if a value was ever
        written, else ``EXTRACTED``. Non-null values move the field to ``PROPOSED``.

        Example:
            fields.propose(workflow, key, {"loan_amount": "30,00,000"})
            fields.propose(workflow, key, {"loan_amount": None})   # discard that edit
        """
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
        """Clear every pending edit for an item and fall back to applied/extracted."""
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
        """
        Record the value SF accepted for a field.

        Kept separate from ``proposed`` so the audit shows both what was asked for and
        what was written; validation compares ``applied`` against the intended value.
        """
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
        """Flag a field whose write was rejected."""
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE work_item_fields
                   SET status = ?, updated_at = ?
                 WHERE workflow = ? AND item_key = ? AND field_key = ?
                """,
                [FieldStatus.REJECTED.value, to_iso(utcnow()), workflow, key, field_key],
            )
