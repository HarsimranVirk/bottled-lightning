"""Review decisions: the operator's local accept/reject judgement (append-only)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from app.core.models import Decision, from_iso, to_iso
from app.core.status import DecisionKind
from app.db.connection import Database

from ._util import opt_str


def _to_decision(row: sqlite3.Row) -> Decision:
    """Map one stored row to a ``Decision``."""
    return Decision(
        workflow=str(row["workflow"]),
        key=str(row["item_key"]),
        decision=DecisionKind(str(row["decision"])),
        reason=opt_str(row["reason"]),
        created_at=_time(row["created_at"]),
    )


def _time(value: str | None) -> datetime:
    """Parse a required stored timestamp."""
    parsed = from_iso(opt_str(value))
    if parsed is None:
        raise ValueError("missing decision timestamp")
    return parsed


class DecisionRepository:
    """
    Append-only review decisions; the newest row per item is the current decision.

    There is no update or delete: undoing a decision writes ``DecisionKind.PENDING``,
    which keeps the audit trail complete. Writes are synchronous SQLite and safe from
    FastAPI's threadpool.

    Example:
        decisions = DecisionRepository(db)
        decisions.record("deviations_z02", key, DecisionKind.ACCEPT, None, utcnow())
        current = decisions.latest("deviations_z02", key)
    """

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def record(
        self,
        workflow: str,
        key: str,
        decision: DecisionKind,
        reason: str | None,
        at: datetime,
    ) -> Decision:
        """
        Append one decision and return it.

        ``reason`` is stored for both kinds (the UI only asks on reject, but nothing
        prevents a note on accept). The caller decides the timestamp so a service call
        can share one ``utcnow()`` across an event and the row.
        """
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO item_decisions (workflow, item_key, decision, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [workflow, key, decision.value, reason, to_iso(at)],
            )
        row = (
            self._db.connect()
            .execute(
                "SELECT workflow, item_key, decision, reason, created_at "
                "FROM item_decisions WHERE id = ?",
                [cursor.lastrowid],
            )
            .fetchone()
        )
        if row is None:
            raise LookupError("decision row disappeared after insert")
        return _to_decision(row)

    def latest(self, workflow: str, key: str) -> Decision | None:
        """The current decision, or ``None`` when the item was never decided."""
        row = (
            self._db.connect()
            .execute(
                """
                SELECT workflow, item_key, decision, reason, created_at
                  FROM item_decisions
                 WHERE workflow = ? AND item_key = ?
                 ORDER BY id DESC LIMIT 1
                """,
                [workflow, key],
            )
            .fetchone()
        )
        return None if row is None else _to_decision(row)

    def latest_for(self, workflow: str, keys: Sequence[str]) -> dict[str, Decision]:
        """
        Current decisions for a page of items in one query.

        Returns only decided items whose newest row is not ``PENDING``; the item list
        calls this per page instead of one query per row.
        """
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        rows = (
            self._db.connect()
            .execute(
                f"""
                SELECT d.workflow, d.item_key, d.decision, d.reason, d.created_at
                  FROM item_decisions d
                 WHERE d.workflow = ?
                   AND d.item_key IN ({placeholders})
                   AND d.id = (
                       SELECT MAX(m.id) FROM item_decisions m
                        WHERE m.workflow = d.workflow AND m.item_key = d.item_key
                   )
                   AND d.decision != ?
                """,
                [workflow, *keys, DecisionKind.PENDING.value],
            )
            .fetchall()
        )
        return {str(row["item_key"]): _to_decision(row) for row in rows}

    def history(
        self, workflow: str, key: str, limit: int = 50
    ) -> list[Decision]:
        """Decision rows for one item, newest first, including undo markers."""
        rows = (
            self._db.connect()
            .execute(
                """
                SELECT workflow, item_key, decision, reason, created_at
                  FROM item_decisions
                 WHERE workflow = ? AND item_key = ?
                 ORDER BY id DESC LIMIT ?
                """,
                [workflow, key, limit],
            )
            .fetchall()
        )
        return [_to_decision(row) for row in rows]
