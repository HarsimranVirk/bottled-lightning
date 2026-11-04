"""One claimed job: pick the workflow, run its pipeline, own the lease and the tabs.

The worker never interprets domain failures — it translates pipeline outcomes and
exceptions into job status (design §8.3) and guarantees the lease is released.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Protocol

from app.core.errors import SessionExpired, TransientBrowserError
from app.core.models import Job
from app.core.registry import WorkflowRegistry
from app.core.repo.events import EventRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import (
    ExtractOutcome,
    JobKind,
    Phase,
    SubmitOutcome,
    WorkItemStatus,
)
from app.pipeline.closure import ClosureResolver
from app.salesforce.tabs import TabSessions

from .auth import AuthGate
from .logger import RepositoryLogger

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 2


class TabSessionFactory(Protocol):
    """Anything that can hand out a fresh tab group."""

    def new_tab_group(self) -> TabSessions:
        """Open a fresh tab group for one job."""
        ...


class Worker:
    """
    Executes one claimed job and owns its lease and tabs.

    The worker is the only place that translates pipeline outcomes into job status,
    and the only place that guarantees the lease is released and the tabs are
    closed — including when the pipeline raises.
    """

    def __init__(
        self,
        name: str,
        registry: WorkflowRegistry,
        items: WorkItemRepository,
        jobs: JobRepository,
        events: EventRepository,
        auth: AuthGate,
        tabs: TabSessionFactory,
        closure: ClosureResolver,
        lease_ttl_s: float = 300.0,
    ) -> None:
        """Wire dependencies; ``name`` identifies this slot in logs."""
        self.name = name
        self._registry = registry
        self._items = items
        self._jobs = jobs
        self._events = events
        self._auth = auth
        self._tabs = tabs
        self._closure = closure
        self._lease_ttl_s = lease_ttl_s

    async def execute(self, job: Job) -> None:
        """
        Run one job to completion, recording its outcome.

        Outcome mapping:

        * extraction ``EXTRACTED``/``SKIPPED`` -> job ``SUCCEEDED``
        * extraction ``FAILED`` -> requeued once, then ``FAILED``
        * submission ``COMPLETED``/``ALREADY_CLOSED`` -> job ``SUCCEEDED``
        * submission ``FAILED`` -> ``FAILED`` (never retried automatically)
        * ``SessionExpired`` -> ``BLOCKED_AUTH`` and the dispatcher pauses
        * anything else -> ``FAILED`` with the exception recorded
        """
        log = RepositoryLogger(job.id, self._jobs)
        try:
            workflow = self._registry.get(job.workflow)
            item = self._items.require(job.workflow, job.item)
        except Exception as exc:
            logger.exception("%s: cannot start job %s", self.name, job.id)
            self._jobs.fail(job.id, f"{type(exc).__name__}: {exc}")
            log(f"cannot start: {type(exc).__name__}: {exc}")
            return

        tabs = self._tabs.new_tab_group()
        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        log(f"{job.kind.value} start: {job.workflow}/{job.item}")
        try:
            if job.kind is JobKind.EXTRACT:
                self._jobs.set_phase(job.id, Phase.EXTRACT)
                extraction = await workflow.extraction.run(item, tabs, log)
                self._finish_extract(job, extraction, log)
            else:
                submission = await workflow.submission.run(item, tabs, log)
                self._finish_submit(job, submission, log)
        except SessionExpired as exc:
            self._auth.on_session_expired(job)
            log(f"session expired — parked for manual login: {exc}")
        except TransientBrowserError as exc:
            retryable = job.attempts < _MAX_ATTEMPTS
            self._jobs.fail(job.id, f"transient: {exc}", retryable=retryable)
            log(f"transient failure (retryable={retryable}): {exc}")
        except Exception as exc:
            logger.exception("%s: job %s failed", self.name, job.id)
            self._jobs.fail(job.id, f"{type(exc).__name__}: {exc}")
            log(f"failed: {type(exc).__name__}: {exc}")
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await tabs.close_all()
            # A closure observed while this job held the lease is resolved now that the
            # job has reached a terminal state (FR-6.11).
            with suppress(Exception):
                self._closure.release_lease(job.workflow, job.item)

    def _finish_extract(
        self, job: Job, outcome: ExtractOutcome, log: RepositoryLogger
    ) -> None:
        """Map an extraction outcome to job status."""
        if outcome in {ExtractOutcome.EXTRACTED, ExtractOutcome.SKIPPED}:
            self._jobs.complete(job.id)
            self._events.emit(
                "job_succeeded",
                workflow=job.workflow,
                item=job.item,
                job_id=job.id,
                detail=outcome.value,
            )
            log(f"done: {outcome.value}")
            return
        retryable = job.attempts < _MAX_ATTEMPTS
        self._jobs.fail(job.id, f"extraction {outcome.value}", retryable=retryable)
        log(f"extraction {outcome.value} (retryable={retryable})")

    def _finish_submit(
        self, job: Job, outcome: SubmitOutcome, log: RepositoryLogger
    ) -> None:
        """Map a submission outcome to job status."""
        if outcome in {SubmitOutcome.COMPLETED, SubmitOutcome.ALREADY_CLOSED}:
            self._jobs.complete(job.id)
            self._events.emit(
                "job_succeeded",
                workflow=job.workflow,
                item=job.item,
                job_id=job.id,
                detail=outcome.value,
            )
            log(f"done: {outcome.value}")
            return
        # Submission failures need a human (changed values, rejected save); retrying
        # automatically would re-write against a state we no longer trust.
        self._jobs.fail(job.id, f"submission {outcome.value}", retryable=False)
        log(f"submission {outcome.value}")

    def _park_submission(self, job: Job) -> None:
        """After a failed submission, make sure the item is not stuck mid-phase.

        Any submission that dies between apply and execute would otherwise leave the
        item in ``SUBMITTING``/``APPLYING``/… forever; moving it to ``NEEDS_REVIEW``
        keeps it visible and retryable (FR-6.9).
        """
        if job.kind is not JobKind.SUBMIT:
            return
        item = self._items.get(job.workflow, job.item)
        if item is None:
            return
        if item.status in {
            WorkItemStatus.SUBMITTING,
            WorkItemStatus.APPLYING,
            WorkItemStatus.VALIDATING,
            WorkItemStatus.EXECUTING,
        }:
            with suppress(Exception):
                self._items.transition(
                    job.workflow,
                    job.item,
                    WorkItemStatus.NEEDS_REVIEW,
                    reason="submission job failed; review and retry",
                )

    async def _heartbeat(self, job_id: int) -> None:
        """Keep renewing the lease while the job runs."""
        interval = max(1.0, self._lease_ttl_s / 3)
        while True:
            await asyncio.sleep(interval)
            self._jobs.heartbeat(job_id, self._lease_ttl_s)
