"""Manual retention policy: fixed cutoffs and the result of one purge.

The repository owns the SQL; this module owns the policy. The current and history windows
are constants so the API and UI cannot widen or shorten retention by accident.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.core.models import utcnow
from app.core.repo.purge import PurgeRepository
from app.db.connection import Database

#: Current work items (and their child/audit rows) are kept for one day.
CURRENT_RETENTION_HOURS = 24

#: Approved-deviation snapshots are kept for three months, expressed as 90 days.
HISTORY_RETENTION_DAYS = 90


class PurgeError(Exception):
    """A purge transaction failed; the route maps it to a 409."""


class PurgeScope(StrEnum):
    """Which independent store a manual purge targets."""

    CURRENT = "current"
    HISTORY = "history"


@dataclass(frozen=True, slots=True)
class PurgeResult:
    """One dry-run or real purge, with the cutoff and per-table deletion counts."""

    scope: PurgeScope
    """Which store the action applied to: ``current`` or ``history``."""

    cutoff: datetime
    """UTC cutoff the server fixed for this run; older rows were eligible."""

    dry_run: bool
    """Whether this is a preview (``deleted`` counts are what *would* go)."""

    deleted: dict[str, int]
    """Rows affected per table name, e.g. ``{"work_items": 12, "jobs": 30}``."""

    @property
    def total(self) -> int:
        """Total rows reported (or deleted) across all tables."""
        return sum(self.deleted.values())


class PurgeService:
    """
    Apply the fixed retention policy through ``PurgeRepository``.

    Called by the dev-only HTTP route and (later) by a manual CLI. The caller may inject
    ``now`` for deterministic tests, but never a cutoff.

    Example:
        result = PurgeService(db).purge(PurgeScope.CURRENT, dry_run=True)
        print(result.cutoff, result.total)
    """

    def __init__(self, db: Database) -> None:
        """Bind the repository and the fixed policy."""
        self._repo = PurgeRepository(db)

    def purge(
        self,
        scope: PurgeScope,
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> PurgeResult:
        """Run one scope at the fixed cutoff and return its counts."""
        current = now if now is not None else utcnow()
        if scope is PurgeScope.CURRENT:
            cutoff = current - timedelta(hours=CURRENT_RETENTION_HOURS)
            try:
                deleted = self._repo.current(cutoff, dry_run)
            except sqlite3.DatabaseError as exc:
                raise PurgeError(str(exc)) from exc
        else:
            cutoff = current - timedelta(days=HISTORY_RETENTION_DAYS)
            try:
                deleted = self._repo.history(cutoff, dry_run)
            except sqlite3.DatabaseError as exc:
                raise PurgeError(str(exc)) from exc
        return PurgeResult(
            scope=scope,
            cutoff=cutoff,
            dry_run=dry_run,
            deleted=deleted,
        )
