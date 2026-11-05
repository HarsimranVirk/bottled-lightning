"""Reconcile one valid list sample against stored items (FR-2.3–2.9, FR-6.13).

This is the only reader of :class:`~app.core.list_view.ListSample`. It never opens a
page and never writes a terminal status: new rows become items with an EXTRACT job,
known rows are touched, and missing rows are handed to the closure resolver.
"""

from __future__ import annotations

from dataclasses import replace

from app.core.list_view import ListSample
from app.core.models import SyncRun
from app.core.repo.attributes import AttributeRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.sync_runs import SyncRunRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import JobKind
from app.core.workflow import Workflow

from .closure import ClosureResolver


class Reconciler:
    def __init__(
        self,
        workflow: Workflow,
        items: WorkItemRepository,
        jobs: JobRepository,
        attributes: AttributeRepository,
        runs: SyncRunRepository,
        closure: ClosureResolver,
    ) -> None:
        self._workflow = workflow
        self._items = items
        self._jobs = jobs
        self._attributes = attributes
        self._runs = runs
        self._closure = closure

    def apply(self, sample: ListSample) -> SyncRun:
        """Apply one refresh and return the recorded run.

        Invalid samples (header/row mismatch) are recorded with a warning and change no
        state — that is the whole point of the validity rule (FR-2.9).
        """
        if not sample.valid:
            return self._record(
                sample,
                warning=(
                    f"header total {sample.header_total} != rows {len(sample.rows)}"
                    if sample.header_total is not None
                    else "header total not readable"
                ),
            )

        added = updated = closed = 0
        seen: set[str] = set()
        for row in sample.rows:
            seen.add(row.key)
            item = self._items.get(self._workflow.name, row.key)
            if item is None:
                self._items.create_present(self._workflow.name, row, sample.captured_at)
                self._jobs.enqueue(self._workflow.name, JobKind.EXTRACT, row.key)
                added += 1
                continue

            was_absent = not item.present
            self._items.touch(
                self._workflow.name,
                row.key,
                sample.captured_at,
                href=row.href or None,
                approved_at=row.approved_at,
            )
            mapped = dict(self._workflow.map_row(row))
            if mapped:
                self._attributes.upsert(self._workflow.name, row.key, mapped)
            if was_absent:
                self._items.begin_epoch(self._workflow.name, row.key)
            updated += 1

        for item in self._items.present(self._workflow.name):
            if item.key in seen:
                continue
            if self._closure.close_if_absent(item, sample.captured_at):
                closed += 1

        # A closure that could not finish on the first absent pass leaves the item
        # present=0, so the present() diff above would never revisit it. Retry every
        # absent, non-terminal, not-yet-closed item on each valid cycle.
        for item in self._items.absent_unclosed(self._workflow.name):
            if item.key in seen:
                continue
            if self._closure.close_if_absent(item, sample.captured_at):
                closed += 1

        return self._record(sample, added=added, updated=updated, closed=closed)

    def _record(
        self,
        sample: ListSample,
        *,
        added: int = 0,
        updated: int = 0,
        closed: int = 0,
        warning: str | None = None,
    ) -> SyncRun:
        run = SyncRun(
            id=0,
            workflow=self._workflow.name,
            captured_at=sample.captured_at,
            header_total=sample.header_total,
            rows_read=len(sample.rows),
            valid=sample.valid,
            warning=warning,
            added=added,
            updated=updated,
            closed=closed,
        )
        run_id = self._runs.record(run)
        return replace(run, id=run_id)
