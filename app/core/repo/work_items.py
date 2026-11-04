"""Work items: presence, lifecycle transitions, presence epochs."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.core.errors import InvalidTransition, LeaseHeld
from app.core.list_view import ListRow
from app.core.models import WorkItem, from_iso, to_iso, utcnow
from app.core.status import (
    TERMINAL_STATUSES,
    ClosureSource,
    WorkItemStatus,
    can_transition,
)
from app.db.connection import Database

from ._util import opt_bool, opt_str, opt_time

_COLUMNS = (
    "workflow, item_key, record_url, status, source, reason, present, epoch, "
    "first_seen, last_seen, absent_since, approved_at, extracted_at, "
    "execute_attempted_at, execute_confirmed_at, closed_at"
)


def _to_item(row: sqlite3.Row) -> WorkItem:
    """Map a row to a ``WorkItem``."""
    return WorkItem(
        workflow=str(row["workflow"]),
        key=str(row["item_key"]),
        record_url=opt_str(row["record_url"]),
        status=WorkItemStatus(str(row["status"])),
        source=ClosureSource(str(row["source"])) if row["source"] is not None else None,
        reason=opt_str(row["reason"]),
        present=opt_bool(row["present"]),
        epoch=int(str(row["epoch"])),
        first_seen=_time(row["first_seen"]),
        last_seen=_time(row["last_seen"]),
        absent_since=opt_time(row["absent_since"]),
        approved_at=opt_str(row["approved_at"]),
        extracted_at=opt_time(row["extracted_at"]),
        execute_attempted_at=opt_time(row["execute_attempted_at"]),
        execute_confirmed_at=opt_time(row["execute_confirmed_at"]),
        closed_at=opt_time(row["closed_at"]),
    )


def _time(value: str | None) -> datetime:
    """Parse a required stored timestamp."""
    parsed = from_iso(opt_str(value))
    if parsed is None:
        raise ValueError("missing timestamp")
    return parsed


class WorkItemRepository:
    """
    Item lifecycle: presence, state transitions and presence epochs.

    Everything workflow-agnostic lives here: creating an item from a list row,
    recording that a refresh saw it, moving it through the state machine, closing it
    and re-entering it when it reappears.

    Example:
        items = WorkItemRepository(db)
        item = items.create_present("deviations_z02", row, sample.captured_at)
        items.transition(item.workflow, item.key, WorkItemStatus.EXTRACTING)
    """

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def get(self, workflow: str, key: str) -> WorkItem | None:
        """One item, or ``None``."""
        row = (
            self._db.connect()
            .execute(
                f"SELECT {_COLUMNS} FROM work_items WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )
            .fetchone()
        )
        return None if row is None else _to_item(row)

    def require(self, workflow: str, key: str) -> WorkItem:
        """One item or raise ``LookupError``."""
        item = self.get(workflow, key)
        if item is None:
            raise LookupError(f"unknown work item {workflow}/{key}")
        return item

    def create_present(self, workflow: str, row: ListRow, at: datetime) -> WorkItem:
        """
        Create the item from a list row if new; idempotent.

        ``INSERT OR IGNORE`` keeps repeated list refreshes cheap: an existing item is
        returned untouched, so its status and values are never reset by a re-scan.

        Example:
            item = items.create_present(workflow, row, at)   # first time: PRESENT
            again = items.create_present(workflow, row, at)  # second time: unchanged
        """
        stamp = to_iso(at)
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO work_items
                    (workflow, item_key, record_url, status, present, epoch, first_seen,
                     last_seen, approved_at)
                VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?)
                """,
                [
                    workflow,
                    row.key,
                    row.href or None,
                    WorkItemStatus.PRESENT.value,
                    stamp,
                    stamp,
                    row.approved_at,
                ],
            )
        return self.require(workflow, row.key)

    def touch(
        self,
        workflow: str,
        key: str,
        at: datetime,
        href: str | None = None,
    ) -> None:
        """
        Refresh presence (and the record URL) on a valid refresh.

        Only called for rows in a *valid* sample. Passing ``href`` also updates
        ``record_url``, which is what lets an EXTRACT job start without the snapshot.
        """
        with self._db.transaction() as conn:
            if href:
                conn.execute(
                    """
                    UPDATE work_items
                       SET last_seen = ?, present = 1, record_url = ?
                     WHERE workflow = ? AND item_key = ?
                    """,
                    [to_iso(at), href, workflow, key],
                )
                return
            conn.execute(
                """
                UPDATE work_items SET last_seen = ?, present = 1
                 WHERE workflow = ? AND item_key = ?
                """,
                [to_iso(at), workflow, key],
            )

    def transition(
        self,
        workflow: str,
        key: str,
        to: WorkItemStatus,
        *,
        reason: str | None = None,
        source: ClosureSource | None = None,
        closed_at: datetime | None = None,
        present: bool | None = None,
        extracted_at: datetime | None = None,
    ) -> WorkItem:
        """
        Apply a state-machine move, refusing terminal status under a lease.

        Three guards make this the single safe writer of item status:

        1. the move must be allowed by ``can_transition`` (else ``InvalidTransition``)
        2. a terminal status is refused while a running job holds a live lease
           (``LeaseHeld``), which is how FR-6.11 prevents closing a row mid-write
        3. only ``SubmitPipeline`` is expected to pass terminal statuses

        Example:
            items.transition(workflow, key, WorkItemStatus.READY, extracted_at=now)
            items.transition(workflow, key, WorkItemStatus.CLOSED,
                             source=ClosureSource.EXTERNAL, reason="already_implemented")
        """
        current = self.require(workflow, key)
        if current.status is not to and not can_transition(current.status, to):
            raise InvalidTransition(f"{workflow}/{key}: {current.status} -> {to}")
        if to in TERMINAL_STATUSES and self._has_active_lease(workflow, key):
            raise LeaseHeld(f"{workflow}/{key}: cannot close while a job lease is held")

        sets = ["status = ?"]
        params: list[str | int] = [to.value]
        if reason is not None:
            sets.append("reason = ?")
            params.append(reason)
        if source is not None:
            sets.append("source = ?")
            params.append(source.value)
        if closed_at is not None:
            sets.append("closed_at = ?")
            params.append(to_iso(closed_at))
        if present is not None:
            sets.append("present = ?")
            params.append(1 if present else 0)
        if extracted_at is not None:
            sets.append("extracted_at = ?")
            params.append(to_iso(extracted_at))
        params.extend([workflow, key])
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE work_items SET {', '.join(sets)} "
                "WHERE workflow = ? AND item_key = ?",
                params,
            )
        return self.require(workflow, key)

    def set_absent(self, workflow: str, key: str, at: datetime) -> None:
        """
        Record that a valid refresh no longer shows the item.

        Flips ``present`` and stamps ``absent_since`` but writes no status: closure
        decisions belong to ``ClosureResolver``, not to the reconciler.
        """
        stamp = to_iso(at)
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE work_items
                   SET present = 0, absent_since = ?, last_seen = ?
                 WHERE workflow = ? AND item_key = ?
                """,
                [stamp, stamp, workflow, key],
            )

    def begin_epoch(self, workflow: str, key: str) -> WorkItem:
        """
        Re-enter after a closure, clearing terminal and extraction state.

        A reappearing item starts a new ``epoch`` and returns to ``PRESENT``. Extraction
        state is cleared too, so the next EXTRACT job actually re-reads the record
        instead of short-circuiting on ``extracted_at`` (FR-6.13).
        """
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE work_items
                   SET epoch = epoch + 1,
                       status = ?,
                       present = 1,
                       absent_since = NULL,
                       source = NULL,
                       reason = NULL,
                       closed_at = NULL,
                       extracted_at = NULL,
                       execute_attempted_at = NULL,
                       execute_confirmed_at = NULL
                 WHERE workflow = ? AND item_key = ?
                """,
                [WorkItemStatus.PRESENT.value, workflow, key],
            )
        return self.require(workflow, key)

    def mark_execute_attempted(self, workflow: str, key: str, at: datetime) -> None:
        """Record that the final SF action was clicked."""
        self._set_time(workflow, key, "execute_attempted_at", at)

    def mark_execute_confirmed(self, workflow: str, key: str, at: datetime) -> None:
        """Record that the final action was observed to succeed."""
        self._set_time(workflow, key, "execute_confirmed_at", at)

    def list(
        self,
        workflow: str,
        status: WorkItemStatus | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WorkItem], int]:
        """
        Page the items, newest-seen first.

        ``query`` matches the key or the reason, which is enough for the UI's search
        box. Returns the page and the total count for pagination.
        """
        where = ["workflow = ?"]
        params: list[str | int] = [workflow]
        if status is not None:
            where.append("status = ?")
            params.append(status.value)
        if query:
            where.append("(item_key LIKE ? OR reason LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])
        clause = " WHERE " + " AND ".join(where)
        conn = self._db.connect()
        total_row = conn.execute(
            f"SELECT COUNT(*) FROM work_items{clause}", params
        ).fetchone()
        total = 0 if total_row is None else int(str(total_row[0]))
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM work_items{clause} "
            "ORDER BY last_seen DESC, item_key LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [_to_item(row) for row in rows], total

    def _set_time(self, workflow: str, key: str, column: str, at: datetime) -> None:
        """Write one timestamp column."""
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE work_items SET {column} = ? WHERE workflow = ? AND item_key = ?",
                [to_iso(at), workflow, key],
            )

    def _has_active_lease(self, workflow: str, key: str) -> bool:
        """Whether a running job holds a live lease on the item."""
        row = (
            self._db.connect()
            .execute(
                """
                SELECT 1 FROM jobs
                 WHERE workflow = ? AND item_key = ? AND status = 'running'
                   AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
                 LIMIT 1
                """,
                [workflow, key, to_iso(utcnow())],
            )
            .fetchone()
        )
        return row is not None
