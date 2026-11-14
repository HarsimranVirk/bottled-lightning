"""LMS 2.0 CL contract approval: open one contract and approve it.

This is a list-less workflow: the operator supplies contract links, so there is nothing
to extract. The submission pipeline validates the stored link, opens the page and calls
the same approval gate `deviations_z02` uses before a Contract Modification write. It
never edits fields and never touches a deviation record. An already-approved contract is
a no-op success; a rejected, unreadable or unconfirmed one parks the item in
``needs_review``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from playwright.async_api import Page

from app.config import TimeoutPolicy
from app.core.errors import SessionExpired, TransientBrowserError
from app.core.models import WorkItem
from app.core.repo.events import EventRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import (
    TERMINAL_STATUSES,
    RefState,
    SubmitOutcome,
    WorkItemStatus,
)
from app.core.workflow import JobLogger
from app.salesforce.tabs import TabProvider
from app.utils.dom import page_closed

logger = logging.getLogger(__name__)

#: The one object link this workflow stores per item.
CONTRACT_KIND = "lms2_cl_contract"

#: Statuses a job may start or resume from. A retry after a transient browser failure
#: re-enters the page without resetting the item, exactly like the deviation pipeline.
_ENTERABLE_STATUSES = frozenset(
    {
        WorkItemStatus.SUBMITTING,
        WorkItemStatus.APPLYING,
        WorkItemStatus.VALIDATING,
        WorkItemStatus.EXECUTING,
    }
)
_WORKING_STATUSES = _ENTERABLE_STATUSES


class ContractApprover(Protocol):
    """The approval-page interaction the pipeline needs, kept separate for tests."""

    async def ensure_approved(self, page: Page, log: JobLogger) -> bool:
        """Return ``True`` when the page is approved, after clicking when pending."""
        ...


class _ApprovalError(Exception):
    """A submission step that must abort and leave the item for review."""


class Lms2ApprovalSubmission:
    """
    One-item approval pipeline for manually supplied LMS 2.0 CL contract links.

    The operator queues the item through the API, which moves it to ``SUBMITTING`` and
    enqueues the job. This pipeline then opens the stored link, asks the approver to
    make the page approved, walks the shared phase markers and returns ``COMPLETED``.
    The worker marks the item terminal afterwards because a list-less workflow has no
    refresh cycle to observe a closure.

    A rejected contract, an unreadable state or an unconfirmed click returns ``FAILED``
    and moves the item to ``NEEDS_REVIEW`` with a plain reason. A retry is an explicit
    operator action (re-queueing the link); nothing retries automatically. A dead tab
    raises :class:`TransientBrowserError` so the worker may requeue once, while an
    expired session raises :class:`SessionExpired` to pause the queue.
    """

    def __init__(
        self,
        workflow: str,
        items: WorkItemRepository,
        refs: PageRefRepository,
        events: EventRepository,
        approver: ContractApprover,
        *,
        timeouts: TimeoutPolicy,
    ) -> None:
        """
        Wire the repositories, the page interaction and the live timeout policy.

        ``timeouts`` is read once per run, so a network-profile change applies to the
        next job rather than one already in flight.
        """
        self._workflow = workflow
        self._items = items
        self._refs = refs
        self._events = events
        self._approver = approver
        self._timeouts = timeouts

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """
        Approve one contract and report the outcome.

        ``COMPLETED`` means the page confirmed the approved state (or already had it).
        ``ALREADY_CLOSED`` means the item was already terminal. ``FAILED`` means the
        contract was rejected, unreadable, unconfirmed, or its link was missing; the
        item is moved to ``NEEDS_REVIEW``. One whole-run budget bounds the job.
        """
        timeouts = self._timeouts.current()
        log(
            "budget: "
            f"profile={timeouts.profile.value} "
            f"action={timeouts.action_ms // 1000}s "
            f"total={timeouts.submission_ms // 1000}s"
        )
        try:
            async with asyncio.timeout(timeouts.submission_ms / 1000):
                return await self._run(item, tabs, log)
        except TimeoutError:
            return self._fail(
                item,
                f"approval did not finish within {timeouts.submission_ms // 1000}s",
                log,
            )
        except SessionExpired:
            raise
        except TransientBrowserError:
            # A dead tab is worth one worker retry, not a parked approval.
            raise
        except _ApprovalError as exc:
            return self._fail(item, str(exc), log)
        except Exception as exc:
            logger.exception("LMS 2.0 approval failed for %s", item.key)
            return self._fail(item, f"{type(exc).__name__}: {exc}", log)

    async def _run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """Read the fresh item, open its link and drive the approval phases."""
        fresh = self._items.get(self._workflow, item.key)
        if fresh is not None:
            item = fresh
        if item.status in TERMINAL_STATUSES:
            log(f"{item.key}: already closed — no approval needed")
            return SubmitOutcome.ALREADY_CLOSED
        if item.status not in _ENTERABLE_STATUSES:
            raise _ApprovalError(f"cannot approve from status {item.status.value}")

        ref = self._refs.for_item(self._workflow, item.key).get(CONTRACT_KIND)
        if ref is None or ref.state is not RefState.FOUND or not ref.url:
            raise _ApprovalError(
                ref.reason
                if ref is not None and ref.reason
                else "missing the LMS 2.0 CL contract link"
            )

        if item.status is WorkItemStatus.SUBMITTING:
            log("phase: applying")
            self._items.transition(
                self._workflow, item.key, WorkItemStatus.APPLYING
            )

        log(f"approve: opening {ref.name or ref.url}")
        page = await tabs.new_page(ref.url)
        try:
            log(f"approve: checking {ref.name or 'contract'} approval state")
            approved = await self._approver.ensure_approved(page, log)
            if not approved:
                raise _ApprovalError(
                    "the contract did not reach an approved state"
                )
            if page_closed(page):
                raise TransientBrowserError("contract page closed during approval")
            if item.status in {
                WorkItemStatus.SUBMITTING,
                WorkItemStatus.APPLYING,
            }:
                log("phase: validating")
                self._items.transition(
                    self._workflow,
                    item.key,
                    WorkItemStatus.VALIDATING,
                    expect=WorkItemStatus.APPLYING,
                )
            log("phase: executing")
            self._items.transition(
                self._workflow,
                item.key,
                WorkItemStatus.EXECUTING,
                reason="approved",
            )
            self._events.emit(
                "approval_confirmed",
                workflow=self._workflow,
                item=item.key,
                detail=ref.name or ref.url,
            )
            log(f"{item.key}: approved")
            return SubmitOutcome.COMPLETED
        finally:
            try:
                await tabs.close_page(page)
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                logger.debug("closing contract page failed: %s", exc)

    def _fail(self, item: WorkItem, reason: str, log: JobLogger) -> SubmitOutcome:
        """Move a mid-approval item to ``NEEDS_REVIEW`` and report the failure."""
        fresh = self._items.get(self._workflow, item.key)
        if fresh is not None and fresh.status in _WORKING_STATUSES:
            try:
                self._items.transition(
                    self._workflow,
                    item.key,
                    WorkItemStatus.NEEDS_REVIEW,
                    reason=reason,
                )
            except Exception:
                logger.exception("could not park %s for review", item.key)
        self._events.emit(
            "approval_failed",
            workflow=self._workflow,
            item=item.key,
            detail=reason,
        )
        log(f"{item.key}: approval failed — {reason}")
        return SubmitOutcome.FAILED
