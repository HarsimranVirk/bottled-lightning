"""Approved-deviation snapshots: the segregated history read model.

The current tables are mutable and may be purged after 24 hours. This repository copies
every accepted deviation into ``approved_deviations`` and its four child tables, and the
History API reads only those copies. The copy is written on accept, refreshed when the
submission or closure changes the item, and removed when the decision stops being an
accept.

All methods are synchronous SQLite calls, safe from FastAPI's threadpool. The repository
never touches Playwright and never reads the token-bearing ``sessions`` table.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.core.models import (
    ApprovedDeviation,
    FieldValue,
    PageRef,
    from_iso,
    to_iso,
    utcnow,
)
from app.core.status import ClosureSource, FieldStatus, WorkItemStatus
from app.db.connection import Database

from ._util import opt_str, opt_time

_PARENT_COLUMNS = (
    "workflow, item_key, epoch, status, source, present, record_url, approved_at, "
    "reason, decided_at, decision_reason, snapshot_at"
)


@dataclass(frozen=True, slots=True)
class HistoryQuery:
    """
    Standard History filter row, translated into one SQL predicate set.

    Contains filters are substring matches; ``keys``/``statuses``/``approved_values``
    are exact sets. ``field_text`` and ``field_values`` are repeated
    ``(field_key, value)`` pairs applied as correlated ``EXISTS`` clauses against
    ``approved_deviation_fields``. All filters compose with AND.
    """

    q: str | None = None
    key: str | None = None
    keys: tuple[str, ...] = ()
    status_text: str | None = None
    statuses: tuple[str, ...] = ()
    approved_at: str | None = None
    approved_values: tuple[str, ...] = ()
    decided_after: str | None = None
    decided_before: str | None = None
    field_text: tuple[tuple[str, str], ...] = ()
    field_values: tuple[tuple[str, str], ...] = ()
    ref_text: tuple[tuple[str, str], ...] = ()
    ref_values: tuple[tuple[str, str], ...] = ()
    limit: int = 25
    offset: int = 0


def _time(value: str | None) -> datetime:
    """Parse a required stored timestamp."""
    parsed = from_iso(opt_str(value))
    if parsed is None:
        raise ValueError("missing approved-history timestamp")
    return parsed


def _to_approved(row: sqlite3.Row) -> ApprovedDeviation:
    """Map one parent row to an ``ApprovedDeviation``."""
    source = opt_str(row["source"])
    return ApprovedDeviation(
        workflow=str(row["workflow"]),
        key=str(row["item_key"]),
        epoch=int(str(row["epoch"])),
        status=WorkItemStatus(str(row["status"])),
        source=ClosureSource(source) if source is not None else None,
        present=bool(int(str(row["present"]))),
        record_url=opt_str(row["record_url"]),
        approved_at=opt_str(row["approved_at"]),
        reason=opt_str(row["reason"]),
        decided_at=_time(row["decided_at"]),
        decision_reason=opt_str(row["decision_reason"]),
        snapshot_at=_time(row["snapshot_at"]),
    )


def _to_field(row: sqlite3.Row) -> FieldValue:
    """Map one snapshot field row to a ``FieldValue``."""
    updated = opt_time(row["updated_at"])
    if updated is None:
        raise ValueError("missing approved field timestamp")
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


class ApprovedHistoryRepository:
    """
    Copy accepted items into the segregated snapshot store and read them back.

    The write side is deliberately app-driven: ``record_accept`` copies the current item
    and all children, ``refresh`` updates an existing snapshot, and ``remove`` deletes it.
    The read side only queries ``approved_*`` tables, so current-data deletion cannot
    blank the History tab.

    Example:
        history = ApprovedHistoryRepository(db)
        history.record_accept("deviations_z02", key, None, utcnow())
        page, total = history.page("deviations_z02", None, 25, 0)
    """

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    # -- writes ------------------------------------------------------------
    def record_accept(
        self,
        workflow: str,
        key: str,
        reason: str | None,
        at: datetime,
    ) -> None:
        """
        Copy the current item into the snapshot store as an accepted deviation.

        Called by ``WorkItemService.decide`` after the accept row is appended. A missing
        current item is a no-op (the item may have been purged between the read and the
        write); otherwise the parent is upserted and every child table is replaced.
        """
        stamp = to_iso(at)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO approved_deviations
                    (workflow, item_key, epoch, status, source, present, record_url,
                     approved_at, reason, decided_at, decision_reason, snapshot_at)
                SELECT workflow, item_key, epoch, status, source, present, record_url,
                       approved_at, reason, ?, ?, ?
                  FROM work_items
                 WHERE workflow = ? AND item_key = ?
                ON CONFLICT(workflow, item_key) DO UPDATE SET
                    epoch = excluded.epoch,
                    status = excluded.status,
                    source = excluded.source,
                    present = excluded.present,
                    record_url = excluded.record_url,
                    approved_at = excluded.approved_at,
                    reason = excluded.reason,
                    decided_at = excluded.decided_at,
                    decision_reason = excluded.decision_reason,
                    snapshot_at = excluded.snapshot_at
                """,
                [
                    stamp,
                    reason,
                    stamp,
                    workflow,
                    key,
                ],
            )
            if cursor.rowcount == 0:
                return
            self._replace_children(conn, workflow, key)

    def refresh(self, workflow: str, key: str) -> None:
        """
        Refresh an existing snapshot from the current item; no-op when absent.

        Called after submit starts, after a submit job finishes and after a closure. The
        accept timestamp and note never move: only the observed state and child rows do.
        """
        stamp = to_iso(utcnow())
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE approved_deviations
                   SET epoch = (SELECT epoch FROM work_items
                                 WHERE workflow = ? AND item_key = ?),
                       status = (SELECT status FROM work_items
                                  WHERE workflow = ? AND item_key = ?),
                       source = (SELECT source FROM work_items
                                  WHERE workflow = ? AND item_key = ?),
                       present = (SELECT present FROM work_items
                                   WHERE workflow = ? AND item_key = ?),
                       record_url = (SELECT record_url FROM work_items
                                      WHERE workflow = ? AND item_key = ?),
                       approved_at = (SELECT approved_at FROM work_items
                                       WHERE workflow = ? AND item_key = ?),
                       reason = (SELECT reason FROM work_items
                                  WHERE workflow = ? AND item_key = ?),
                       snapshot_at = ?
                 WHERE workflow = ? AND item_key = ?
                   AND EXISTS (SELECT 1 FROM work_items
                                WHERE workflow = ? AND item_key = ?)
                """,
                [
                    workflow,
                    key,
                    workflow,
                    key,
                    workflow,
                    key,
                    workflow,
                    key,
                    workflow,
                    key,
                    workflow,
                    key,
                    workflow,
                    key,
                    stamp,
                    workflow,
                    key,
                    workflow,
                    key,
                ],
            )
            if cursor.rowcount == 0:
                return
            self._replace_children(conn, workflow, key)

    def remove(self, workflow: str, key: str) -> None:
        """Delete a snapshot and all of its child rows; idempotent."""
        with self._db.transaction() as conn:
            self._delete_children(conn, workflow, key)
            conn.execute(
                "DELETE FROM approved_deviations WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )

    def _replace_children(
        self, conn: sqlite3.Connection, workflow: str, key: str
    ) -> None:
        """Replace every snapshot child row for one item from the current tables."""
        self._delete_children(conn, workflow, key)
        conn.execute(
            """
            INSERT INTO approved_deviation_fields
                (workflow, item_key, field_key, extracted, last_synced, proposed,
                 applied, status, updated_at)
            SELECT workflow, item_key, field_key, extracted, last_synced, proposed,
                   applied, status, updated_at
              FROM work_item_fields
             WHERE workflow = ? AND item_key = ?
            """,
            [workflow, key],
        )
        conn.execute(
            """
            INSERT INTO approved_deviation_attributes
                (workflow, item_key, name, value)
            SELECT workflow, item_key, name, value
              FROM work_item_attributes
             WHERE workflow = ? AND item_key = ?
            """,
            [workflow, key],
        )
        conn.execute(
            """
            INSERT INTO approved_deviation_refs
                (workflow, item_key, kind, name, url)
            SELECT workflow, item_key, kind, name, url
              FROM work_item_refs
             WHERE workflow = ? AND item_key = ?
            """,
            [workflow, key],
        )
        conn.execute(
            """
            INSERT INTO approved_deviation_edits
                (workflow, item_key, field_key, old_value, new_value, created_at)
            SELECT workflow, item_key, field_key, old_value, new_value, created_at
              FROM work_item_edits
             WHERE workflow = ? AND item_key = ?
            """,
            [workflow, key],
        )

    def _delete_children(
        self, conn: sqlite3.Connection, workflow: str, key: str
    ) -> None:
        """Delete snapshot children for one item (used by replace and remove)."""
        for table in (
            "approved_deviation_fields",
            "approved_deviation_attributes",
            "approved_deviation_refs",
            "approved_deviation_edits",
        ):
            conn.execute(
                f"DELETE FROM {table} WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )

    # -- reads -------------------------------------------------------------
    def page(
        self, workflow: str, query: HistoryQuery
    ) -> tuple[list[ApprovedDeviation], int]:
        """
        Page accepted snapshots, newest accept first, applying every filter with AND.

        Returns the page and the filtered total, so server-side pagination stays correct
        when any text or checkbox filter is active.
        """
        where = ["workflow = ?"]
        params: list[str | int] = [workflow]
        if query.q:
            where.append(
                "(item_key LIKE ? OR reason LIKE ? OR decision_reason LIKE ?)"
            )
            like = f"%{query.q}%"
            params.extend([like, like, like])
        if query.key:
            where.append("item_key LIKE ?")
            params.append(f"%{query.key}%")
        if query.keys:
            placeholders = ",".join("?" for _ in query.keys)
            where.append(f"item_key IN ({placeholders})")
            params.extend(query.keys)
        if query.status_text:
            where.append("status LIKE ?")
            params.append(f"%{query.status_text}%")
        if query.statuses:
            placeholders = ",".join("?" for _ in query.statuses)
            where.append(f"status IN ({placeholders})")
            params.extend(query.statuses)
        if query.approved_at:
            where.append("approved_at LIKE ?")
            params.append(f"%{query.approved_at}%")
        if query.approved_values:
            placeholders = ",".join("?" for _ in query.approved_values)
            where.append(f"approved_at IN ({placeholders})")
            params.extend(query.approved_values)
        if query.decided_after:
            where.append("substr(decided_at, 1, 10) >= ?")
            params.append(query.decided_after)
        if query.decided_before:
            where.append("substr(decided_at, 1, 10) <= ?")
            params.append(query.decided_before)
        for field_key, text in query.field_text:
            where.append(
                "EXISTS (SELECT 1 FROM approved_deviation_fields f "
                "WHERE f.workflow = approved_deviations.workflow "
                "AND f.item_key = approved_deviations.item_key "
                "AND f.field_key = ? "
                "AND COALESCE(f.proposed, f.extracted, f.applied, '') LIKE ?)"
            )
            params.extend([field_key, f"%{text}%"])
        for field_key, value in query.field_values:
            where.append(
                "EXISTS (SELECT 1 FROM approved_deviation_fields f "
                "WHERE f.workflow = approved_deviations.workflow "
                "AND f.item_key = approved_deviations.item_key "
                "AND f.field_key = ? "
                "AND COALESCE(f.proposed, f.extracted, f.applied, '') = ?)"
            )
            params.extend([field_key, value])
        for ref_kind, text in query.ref_text:
            where.append(
                "EXISTS (SELECT 1 FROM approved_deviation_refs r "
                "WHERE r.workflow = approved_deviations.workflow "
                "AND r.item_key = approved_deviations.item_key "
                "AND r.kind = ? "
                "AND r.name LIKE ?)"
            )
            params.extend([ref_kind, f"%{text}%"])
        for ref_kind, value in query.ref_values:
            where.append(
                "EXISTS (SELECT 1 FROM approved_deviation_refs r "
                "WHERE r.workflow = approved_deviations.workflow "
                "AND r.item_key = approved_deviations.item_key "
                "AND r.kind = ? "
                "AND r.name = ?)"
            )
            params.extend([ref_kind, value])

        clause = " WHERE " + " AND ".join(where)
        conn = self._db.connect()
        total_row = conn.execute(
            f"SELECT COUNT(*) FROM approved_deviations{clause}", params
        ).fetchone()
        total = 0 if total_row is None else int(str(total_row[0]))
        rows = conn.execute(
            f"SELECT {_PARENT_COLUMNS} FROM approved_deviations{clause} "
            "ORDER BY decided_at DESC, item_key LIMIT ? OFFSET ?",
            [*params, query.limit, query.offset],
        ).fetchall()
        return [_to_approved(row) for row in rows], total

    def get(self, workflow: str, key: str) -> ApprovedDeviation | None:
        """One approved snapshot, or ``None``."""
        row = (
            self._db.connect()
            .execute(
                f"SELECT {_PARENT_COLUMNS} FROM approved_deviations "
                "WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )
            .fetchone()
        )
        return None if row is None else _to_approved(row)

    def fields(self, workflow: str, key: str) -> dict[str, FieldValue]:
        """Snapshot field values for one item, keyed by catalogue field."""
        rows = (
            self._db.connect()
            .execute(
                "SELECT workflow, item_key, field_key, extracted, last_synced, "
                "proposed, applied, status, updated_at "
                "FROM approved_deviation_fields "
                "WHERE workflow = ? AND item_key = ? ORDER BY field_key",
                [workflow, key],
            )
            .fetchall()
        )
        return {str(row["field_key"]): _to_field(row) for row in rows}

    def attributes(self, workflow: str, key: str) -> dict[str, str | None]:
        """Snapshot read-only attributes for one item."""
        rows = (
            self._db.connect()
            .execute(
                "SELECT name, value FROM approved_deviation_attributes "
                "WHERE workflow = ? AND item_key = ? ORDER BY name",
                [workflow, key],
            )
            .fetchall()
        )
        return {
            str(row["name"]): None if row["value"] is None else str(row["value"])
            for row in rows
        }

    def refs(self, workflow: str, key: str) -> dict[str, PageRef]:
        """Snapshot object links for one item, keyed by object kind."""
        rows = (
            self._db.connect()
            .execute(
                "SELECT kind, name, url FROM approved_deviation_refs "
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

    def refs_for(
        self, workflow: str, keys: Sequence[str]
    ) -> dict[str, dict[str, PageRef]]:
        """
        Snapshot object links for a whole page, keyed by item then object kind.

        Called once per History page so a 25-row page costs one query instead of 25.
        Uses the ``(workflow, item_key, kind)`` primary-key prefix. An empty ``keys``
        sequence returns an empty mapping without touching the database.
        """
        if not keys:
            return {}
        placeholders = ", ".join("?" for _ in keys)
        rows = (
            self._db.connect()
            .execute(
                "SELECT item_key, kind, name, url FROM approved_deviation_refs "
                f"WHERE workflow = ? AND item_key IN ({placeholders}) "
                "ORDER BY item_key, kind",
                [workflow, *keys],
            )
            .fetchall()
        )
        grouped: dict[str, dict[str, PageRef]] = {}
        for row in rows:
            item_key = str(row["item_key"])
            ref = PageRef(
                workflow=workflow,
                item=item_key,
                kind=str(row["kind"]),
                name=str(row["name"]),
                url=str(row["url"]),
            )
            grouped.setdefault(item_key, {})[ref.kind] = ref
        return grouped

    def edits(
        self, workflow: str, key: str, limit: int = 50
    ) -> list[tuple[str, str | None, str | None, str]]:
        """Snapshot edits for one item, newest first, in the current-detail tuple shape."""
        rows = (
            self._db.connect()
            .execute(
                "SELECT field_key, old_value, new_value, created_at "
                "FROM approved_deviation_edits "
                "WHERE workflow = ? AND item_key = ? ORDER BY id DESC LIMIT ?",
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
