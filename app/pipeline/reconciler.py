"""Reconcile one valid list sample against stored items (FR-2.3–2.9, FR-6.13).

This is the only reader of :class:`~app.core.list_view.ListSample`. It never opens a
page and never writes a terminal status: new rows become items, extraction is queued
only when the row carries a record link, known rows are touched, and missing rows are
handed to the closure resolver.

It also audits items that cannot make progress on their own — an extraction that never
finished, or a ``READY`` item whose stored links are incomplete — and turns them into
``NEEDS_REVIEW`` cards so the operator can retry. Nothing here retries automatically.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from app.core.errors import InvalidTransition
from app.core.list_view import ListSample
from app.core.models import SyncRun
from app.core.repo.attributes import AttributeRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sync_runs import SyncRunRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import JobKind, WorkItemStatus
from app.core.workflow import Workflow

from .closure import ClosureResolver

logger = logging.getLogger(__name__)

#: Shown when an item was left mid-extraction with no job to finish it.
ABANDONED_EXTRACTION_REASON = "Extraction didn't finish — retry it"

#: Shown when a ``READY`` item's stored links were never fully extracted.
INCOMPLETE_EXTRACTION_REASON = "Couldn't read some of this deviation's pages — retry it"


class Reconciler:
    """
    Apply one refresh of a workflow's list view to its stored items.

    Called by the watcher after a successful list read, on the watcher thread, with the
    item/job repositories already wired. It is the only place that creates items and
    queues extraction jobs, so the "no link, no job" rule lives here and nowhere else.
    """

    def __init__(
        self,
        workflow: Workflow,
        items: WorkItemRepository,
        jobs: JobRepository,
        attributes: AttributeRepository,
        refs: PageRefRepository,
        runs: SyncRunRepository,
        closure: ClosureResolver,
    ) -> None:
        """Store the workflow and its repositories; no work happens here."""
        self._workflow = workflow
        self._items = items
        self._jobs = jobs
        self._attributes = attributes
        self._refs = refs
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
                # A row with no record link has nothing to open yet. It stays present
                # and the refresh that supplies the link queues the job.
                if row.href:
                    self._jobs.enqueue(self._workflow.name, JobKind.EXTRACT, row.key)
                added += 1
                continue

            was_absent = not item.present
            had_url = bool(item.record_url)
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
            elif row.href and not had_url and item.extracted_at is None:
                # The row was first seen from the Printable View before the live list
                # exposed its record link. Now that the URL is here, extract it (FR-3.9).
                self._jobs.enqueue(self._workflow.name, JobKind.EXTRACT, row.key)
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

        self._audit(seen)

        return self._record(sample, added=added, updated=updated, closed=closed)

    def _audit(self, seen: set[str]) -> None:
        """
        Move items that cannot progress on their own to ``NEEDS_REVIEW``.

        Two states are repaired, both for rows still in the list:

        ``EXTRACTING`` with no active job — the extraction ended without recording an
        outcome (worker crash, persistence error, stale lease at the attempt cap). Left
        alone the item would sit invisible forever, so it becomes operator work.

        ``READY`` with an incomplete link set — data extracted before link states
        existed, or a required link that has since been proven absent. Readiness must
        mean "every required link is usable", so the item goes back for review.

        Items outside this sample are skipped: the closure resolver owns those.
        """
        ready_refs = self._refs.for_items_in_status(
            self._workflow.name, WorkItemStatus.READY
        )
        for item in self._items.present(self._workflow.name):
            if item.key not in seen:
                continue
            if item.status is WorkItemStatus.EXTRACTING:
                if self._jobs.active_for(self._workflow.name, item.key) is not None:
                    continue
                reason = ABANDONED_EXTRACTION_REASON
            elif item.status is WorkItemStatus.READY:
                gap = self._workflow.incomplete_ref(ready_refs.get(item.key, {}))
                if gap is None:
                    continue
                reason = gap.reason or INCOMPLETE_EXTRACTION_REASON
            else:
                continue
            logger.warning(
                "%s/%s: %s -> needs_review (%s)",
                self._workflow.name,
                item.key,
                item.status.value,
                reason,
            )
            try:
                self._items.transition(
                    self._workflow.name,
                    item.key,
                    WorkItemStatus.NEEDS_REVIEW,
                    expect=item.status,
                    reason=reason,
                )
            except InvalidTransition:
                # The item moved on between the snapshot and the write (a job finished
                # while this refresh was running). Its fresh status wins.
                logger.debug(
                    "%s/%s: audit skipped, status changed during the refresh",
                    self._workflow.name,
                    item.key,
                )

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
