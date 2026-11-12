"""Typed links from an item to the SF objects involved in it."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from app.core.models import PageRef
from app.core.status import RefState, WorkItemStatus
from app.db.connection import Database


def _to_ref(row: sqlite3.Row, workflow: str, key: str) -> PageRef:
    """Map one stored ref row to a ``PageRef``; the v6 migration guarantees the columns."""
    reason = row["reason"]
    return PageRef(
        workflow=workflow,
        item=key,
        kind=str(row["kind"]),
        name=str(row["name"]),
        url=str(row["url"]),
        state=RefState(str(row["state"])),
        reason=None if reason is None else str(reason),
    )


class PageRefRepository:
    """
    Typed links from an item to the SF objects involved in it.

    Every expected object kind has exactly one row after extraction: a ``FOUND`` row
    with a usable URL, or an ``ABSENT``/``UNRESOLVED`` row with empty name/url and a
    reason. Callers must branch on ``state`` before using ``url``.
    """

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    def for_item(self, workflow: str, key: str) -> dict[str, PageRef]:
        """Refs for one item, keyed by object kind."""
        rows = (
            self._db.connect()
            .execute(
                "SELECT kind, name, url, state, reason FROM work_item_refs "
                "WHERE workflow = ? AND item_key = ? ORDER BY kind",
                [workflow, key],
            )
            .fetchall()
        )
        return {str(row["kind"]): _to_ref(row, workflow, key) for row in rows}

    def for_items_in_status(
        self, workflow: str, status: WorkItemStatus
    ) -> dict[str, dict[str, PageRef]]:
        """
        Refs for every present item in ``status``, keyed by item then object kind.

        One ``LEFT JOIN`` instead of a query per item, used by the reconciler's audit to
        check every ``READY`` item's links during a refresh. The driving side is
        ``work_items_status(workflow, status)`` and each item is five primary-key
        lookups, so the cost does not grow with a statement per item.

        ``LEFT`` is load-bearing: an item with **no** ref rows at all still appears, with
        an empty mapping. Those are exactly the legacy items the audit exists for, and an
        inner join would silently skip them.
        """
        rows = (
            self._db.connect()
            .execute(
                """
                SELECT w.item_key, r.kind, r.name, r.url, r.state, r.reason
                  FROM work_items w
                  LEFT JOIN work_item_refs r
                         ON r.workflow = w.workflow AND r.item_key = w.item_key
                 WHERE w.workflow = ? AND w.status = ? AND w.present = 1
                 ORDER BY w.item_key, r.kind
                """,
                [workflow, status.value],
            )
            .fetchall()
        )
        grouped: dict[str, dict[str, PageRef]] = {}
        for row in rows:
            key = str(row["item_key"])
            bucket = grouped.setdefault(key, {})
            if row["kind"] is None:
                continue
            ref = _to_ref(row, workflow, key)
            bucket[ref.kind] = ref
        return grouped

    def replace(self, workflow: str, key: str, refs: Sequence[PageRef]) -> None:
        """
        Replace all refs for an item atomically.

        Extraction discovers refs in parallel, so it collects them first and writes once
        — the item never holds a half-set of links. Re-running extraction therefore also
        drops links that no longer exist in SF, and refreshes each kind's state.
        """
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM work_item_refs WHERE workflow = ? AND item_key = ?",
                [workflow, key],
            )
            for ref in refs:
                conn.execute(
                    """
                    INSERT INTO work_item_refs
                        (workflow, item_key, kind, name, url, state, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        workflow,
                        key,
                        ref.kind,
                        ref.name,
                        ref.url,
                        ref.state.value,
                        ref.reason,
                    ],
                )
