"""Closing items that left the list view (FR-2.6, FR-2.8, FR-6.11).

The resolver is the only writer of closure outcomes. It decides *what* a disappearance
means from our own action record, and defers the decision while a job still holds the
item's lease so a worker is never writing to a row the queue considers closed.
"""

from __future__ import annotations

from datetime import datetime

from app.core.models import WorkItem, to_iso, utcnow
from app.core.repo.events import EventRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import (
    TERMINAL_STATUSES,
    ClosureSource,
    JobStatus,
    WorkItemStatus,
)

_UNCONFIRMED_REASON = "implement_unconfirmed"
_EXTERNAL_REASON = "already_implemented"


class ClosureResolver:
    def __init__(
        self,
        items: WorkItemRepository,
        jobs: JobRepository,
        events: EventRepository,
    ) -> None:
        self._items = items
        self._jobs = jobs
        self._events = events

    def close_if_absent(self, item: WorkItem, observed_at: datetime) -> bool:
        """Close an item missing from a valid refresh. Returns whether it closed.

        Called by the reconciler for every known item that a valid sample no longer
        contains. If a running job holds a live lease, the item is only marked absent
        and moves to ``ABSENT_PENDING``; the resolver finishes the job on lease release.

        Example: a deviation implemented elsewhere between two refreshes becomes
        ``closed`` with ``source="external"`` — no implement click was recorded.
        """
        if item.status in TERMINAL_STATUSES:
            return False
        self._items.set_absent(item.workflow, item.key, observed_at)
        if self._has_live_lease(item):
            if item.status is not WorkItemStatus.ABSENT_PENDING:
                self._items.transition(
                    item.workflow, item.key, WorkItemStatus.ABSENT_PENDING, present=False
                )
            return False
        return self._finish(item, observed_at)

    def release_lease(self, workflow: str, key: str) -> None:
        """Resolve a deferred closure once the item's job has released its lease.

        Called by the worker in its ``finally`` block, after the job reached a terminal
        state but before the lease is considered free. Does nothing unless the item is
        ``ABSENT_PENDING`` and no other running job holds it.

        Example: a SUBMIT was mid-apply when the item vanished; the item sat in
        ``ABSENT_PENDING`` and is completed or closed here, never mid-write.
        """
        item = self._items.get(workflow, key)
        if item is None or item.status is not WorkItemStatus.ABSENT_PENDING:
            return
        if self._has_live_lease(item):
            return
        self._finish(item, utcnow())

    def _finish(self, item: WorkItem, closed_at: datetime) -> bool:
        status, source, reason = self._attribution(item)
        # Always pass through ABSENT_PENDING: every non-terminal state allows it, and it
        # allows both terminal states, so the move is legal from any starting point.
        if item.status is not WorkItemStatus.ABSENT_PENDING:
            self._items.transition(
                item.workflow, item.key, WorkItemStatus.ABSENT_PENDING, present=False
            )
        self._items.transition(
            item.workflow,
            item.key,
            status,
            source=source,
            reason=reason,
            closed_at=closed_at,
            present=False,
        )
        self._jobs.cancel_active_for(item.workflow, item.key)
        self._events.emit(
            "closed",
            workflow=item.workflow,
            item=item.key,
            detail=f"{status.value}/{source.value}",
        )
        return True

    def _attribution(
        self, item: WorkItem
    ) -> tuple[WorkItemStatus, ClosureSource, str | None]:
        """Attribute a closure from our own record of the final action (FR-2.8)."""
        if item.execute_confirmed_at is not None:
            return WorkItemStatus.COMPLETED, ClosureSource.SYSTEM, None
        if item.execute_attempted_at is not None:
            return WorkItemStatus.COMPLETED, ClosureSource.SYSTEM, _UNCONFIRMED_REASON
        return WorkItemStatus.CLOSED, ClosureSource.EXTERNAL, _EXTERNAL_REASON

    def _has_live_lease(self, item: WorkItem) -> bool:
        active = self._jobs.active_for(item.workflow, item.key)
        if active is None or active.status is not JobStatus.RUNNING:
            return False
        expires = active.lease_expires_at
        return expires is not None and to_iso(expires) > to_iso(utcnow())
