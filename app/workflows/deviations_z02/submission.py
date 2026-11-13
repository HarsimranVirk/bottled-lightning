"""Z02 submission: apply → validate → implement.

The pipeline reads the current SF values before writing (FR-6.2), writes every catalogue
target that has a proposed value, reads them back, and only then runs the final action on
the deviation record: it reads the ``Implemented__c`` tick and clicks **Implemented** when
the tick is absent (FR-6.5–6.7). A tick already present is an external closure, never
claimed as ours (FR-6.16).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from playwright.async_api import Page

from app.config import SubmissionTimeouts, TimeoutPolicy
from app.core.errors import SessionExpired, TransientBrowserError
from app.core.field import EditableField, FieldTarget, ValueType, normalise
from app.core.models import PageRef, WorkItem, utcnow
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import (
    TERMINAL_STATUSES,
    SubmitOutcome,
    WorkItemStatus,
    WriteOutcome,
)
from app.core.workflow import JobLogger, RefKind, incomplete_ref
from app.salesforce.adapters import (
    AdapterRegistry,
    ObjectAdapter,
    describe_target,
)
from app.salesforce.tabs import TabProvider
from app.utils.dom import page_closed

from .adapters.deviation_record import DeviationRecordAdapter
from .catalog import DeviationObject

logger = logging.getLogger(__name__)

_WORKING_SUBMIT_STATUSES = frozenset(
    {
        WorkItemStatus.SUBMITTING,
        WorkItemStatus.APPLYING,
        WorkItemStatus.VALIDATING,
        WorkItemStatus.EXECUTING,
    }
)
_ENTERABLE_SUBMIT_STATUSES = frozenset(
    {
        WorkItemStatus.READY,
        WorkItemStatus.EDITING,
        WorkItemStatus.NEEDS_REVIEW,
    }
)


class _SubmitError(Exception):
    """A submission step that must abort and leave the item for review."""


@dataclass(frozen=True, slots=True)
class _Plan:
    """One proposed field, its canonical intended value and whether it was applied."""

    field: EditableField
    """The catalogue entry being written, which carries the target labels."""

    intended: str
    """Canonical value the operator proposed, already normalised for comparison."""

    applied: bool
    """Whether an earlier attempt already wrote this field, so a retry may skip it."""

    @property
    def targets(self) -> tuple[FieldTarget, ...]:
        """The SF targets this field fans out to."""
        return self.field.targets


@dataclass(frozen=True, slots=True)
class _ObjectGroup:
    """All targets that live on one SF object, plus the page ref that opens it."""

    kind: str
    """Object kind whose page carries these targets, e.g. ``cl_contract``."""

    ref: PageRef
    """The link used to open that page; its ``state`` was already validated."""

    values: Mapping[FieldTarget, str]
    """Canonical values to write, keyed by the exact target on this object."""

    @property
    def targets(self) -> tuple[FieldTarget, ...]:
        """The targets to read or write on this object."""
        return tuple(self.values)


def _canonical(value: str | None, value_type: ValueType) -> str | None:
    """Normalise a stored/display value, or ``None`` when it cannot be parsed."""
    if value is None:
        return None
    try:
        return normalise(value, value_type)
    except ValueError:
        return None


def _is_closed(item: WorkItem) -> bool:
    """Whether the item is already gone (terminal or absent from a valid refresh)."""
    return (
        item.status in TERMINAL_STATUSES
        or not item.present
        or item.absent_since is not None
    )


class DeviationsZ02Submission:
    """
    Submission pipeline for Z02 (class design, section 9.3).

    This is a write-and-verify pipeline, not a conflict detector. Every target's current
    value is read before the first write and recorded for the operator's audit, and an
    already-applied target is skipped on a retry. A current value that differs from the
    last watcher snapshot does **not** block the write: description-derived values are
    not guaranteed to be true, so the operator's proposal is authoritative.

    Every write is read back before the item leaves ``validating``. Any rejected write or
    read-back mismatch is a failure gate: the item moves to ``NEEDS_REVIEW``, the job
    fails, and the operator is notified. There is no automatic rollback in this phase;
    the per-target truth shows exactly what was and was not written.

    After validation the pipeline implements the deviation on its record page. A
    pre-existing tick returns ``ALREADY_CLOSED`` (external attribution); otherwise it
    clicks **Implemented** and confirms on the tick, returning ``COMPLETED``. The job
    never writes the terminal status itself: a live lease forbids it, so the closure
    resolver applies it on the next valid refresh.
    """

    def __init__(
        self,
        workflow: str,
        items: WorkItemRepository,
        fields: FieldValueRepository,
        refs: PageRefRepository,
        events: EventRepository,
        adapters: AdapterRegistry,
        catalog: Sequence[EditableField],
        *,
        ref_kinds: tuple[RefKind, ...],
        timeouts: TimeoutPolicy,
    ) -> None:
        """
        Wire repositories, adapters, the catalogue, the declared link kinds and the
        live timeout policy.

        ``ref_kinds`` is the same declaration extraction uses. The pipeline refuses to
        start when any required link is not ``FOUND``, so a submission can never try to
        open an empty URL. ``timeouts`` is read once per run (see :meth:`run`), so a
        profile change changes the next job, never one already in flight.
        """
        self._workflow = workflow
        self._items = items
        self._fields = fields
        self._refs = refs
        self._events = events
        self._adapters = adapters
        self._catalog = tuple(catalog)
        self._ref_kinds = ref_kinds
        self._timeouts = timeouts

    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """
        Apply, validate and implement one item's proposed values.

        Outcomes: ``COMPLETED`` (apply + read-back + Implement confirmed),
        ``ALREADY_CLOSED`` (item gone, or already ticked in Salesforce),
        ``FAILED`` (rejected write, missing link, validation mismatch or unconfirmed
        click; the item moves to ``NEEDS_REVIEW``). A failed run does not roll back
        values that were already written; the per-target truth is recorded and the
        operator is notified.

        A tab that dies mid-job raises :class:`TransientBrowserError` instead of
        returning an outcome, so the worker retries the job once rather than parking a
        half-written submission as a rejected write. The item is left in its working
        status, which the retry accepts.

        Three budgets bound the run, all snapshotted here so one job runs under one
        profile: each object read, each object write, and the run as a whole. A write
        that overruns is recorded ``UNKNOWN`` and the remaining objects are still
        attempted, because this pipeline never retries a submission on its own — every
        group that lands is manual work the operator does not have to redo.
        """
        timeouts = self._timeouts.current()
        log(
            "budget: "
            f"profile={timeouts.profile.value} "
            f"action={timeouts.action_ms // 1000}s "
            f"read={timeouts.stage_read_ms // 1000}s "
            f"write={timeouts.stage_write_ms // 1000}s "
            f"total={timeouts.submission_ms // 1000}s"
        )
        try:
            # Re-read the item: the watcher may have recorded absence since the worker
            # claimed the job, and that is exactly the precheck FR-6.2/6.6 requires.
            fresh = self._items.get(self._workflow, item.key)
            if fresh is not None:
                item = fresh
            plans = self._plans(item)
            if not plans:
                raise _SubmitError("no proposed values to submit")
            if _is_closed(item):
                return self._already_closed(item, "item is not present in the list", log)
            if item.status is WorkItemStatus.EXECUTING:
                # A crash between the click and its confirmation was requeued. The
                # values were already validated; only the final action needs finishing.
                return await self._execute(item, tabs, log)

            self._require_links(item.key)
            item = self._begin(item)
            groups = self._groups(item.key, plans)
            pages: dict[str, Page] = {}
            try:
                async with asyncio.timeout(timeouts.submission_ms / 1000):
                    current = await self._read_all(
                        groups, tabs, pages, log, "precheck", timeouts
                    )
                    self._audit_precheck(item, groups, current, log)
                    log("phase: applying")
                    self._items.transition(
                        self._workflow, item.key, WorkItemStatus.APPLYING
                    )
                    outcomes = await self._write_all(
                        groups, pages, current, plans, log, timeouts
                    )
                    self._record_apply(item.key, plans, outcomes, log)
                    rejected = [
                        f"{target.object_kind}/{target.label}={result.value}"
                        for target, result in outcomes.items()
                        if result is not WriteOutcome.SAVED
                    ]
                    if rejected:
                        raise _SubmitError(
                            "writes not accepted: " + ", ".join(rejected)
                        )

                    log("phase: validating")
                    self._items.transition(
                        self._workflow, item.key, WorkItemStatus.VALIDATING
                    )
                    # The apply tabs were just mutated by inline-edit saves, and Lightning
                    # re-renders (and lazily reloads) the record around them. Re-open the
                    # pages so validation reads what Salesforce stored, not the DOM the
                    # writes left behind — a stale/empty read must not fail the item.
                    await self._close_pages(pages, tabs, "submission")
                    readback = await self._read_all(
                        groups, tabs, pages, log, "readback", timeouts
                    )
                    self._check_readback(item.key, plans, readback, log)
                    fresh = self._items.require(self._workflow, item.key)
                    if _is_closed(fresh):
                        return self._already_closed(
                            item, "item disappeared during validation", log
                        )
                    return await self._execute(fresh, tabs, log)
            finally:
                # Outside the budget on purpose: cleanup must run even when it fired.
                await self._close_pages(pages, tabs, "submission")
        except TimeoutError:
            return self._fail(
                item,
                f"submission did not finish within "
                f"{timeouts.submission_ms // 1000}s",
                log,
            )
        except SessionExpired:
            raise
        except TransientBrowserError:
            # A dead tab is worth one retry, not a parked half-written submission.
            raise
        except _SubmitError as exc:
            return self._fail(item, str(exc), log)
        except Exception as exc:
            logger.exception("submission failed for %s", item.key)
            return self._fail(item, f"{type(exc).__name__}: {exc}", log)

    async def _execute(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """
        Run the final action on the deviation record page.

        Called after validation, and again for a requeued job whose item is already
        ``EXECUTING``. A tick already present returns ``ALREADY_CLOSED`` without clicking
        or writing execute timestamps (FR-6.16). Otherwise it marks the attempt, clicks
        **Implemented**, confirms on the tick and returns ``COMPLETED``; an unconfirmed
        click raises so the item is parked for review with the attempt recorded (FR-6.7).
        """
        record_url = item.record_url
        if not record_url:
            raise _SubmitError("item has no deviation record URL")
        adapter = self._adapters.get(DeviationObject.DEVIATION.value)
        if not isinstance(adapter, DeviationRecordAdapter):
            raise _SubmitError("deviation adapter cannot run the final action")

        page = await adapter.open_record(tabs, record_url)
        try:
            log("execute: deviation: record page opened")
            implemented = await adapter.is_implemented(page, log)
            if implemented is None:
                raise _SubmitError(
                    "Implemented checkbox not found on the deviation record"
                )
            if implemented:
                return self._already_closed(
                    item, "already implemented in Salesforce", log
                )

            if item.status is not WorkItemStatus.EXECUTING:
                log("phase: executing")
                self._items.transition(
                    self._workflow, item.key, WorkItemStatus.EXECUTING
                )
            self._items.mark_execute_attempted(self._workflow, item.key, utcnow())
            log(f"{item.key}: running the final action")
            if not await adapter.implement(page, log):
                raise _SubmitError(
                    "Implement clicked but the Implemented checkbox did not turn on"
                )
            self._items.mark_execute_confirmed(self._workflow, item.key, utcnow())
            self._events.emit(
                "submit_completed",
                workflow=self._workflow,
                item=item.key,
                detail="implemented",
            )
            log(f"{item.key}: implemented")
            return SubmitOutcome.COMPLETED
        finally:
            try:
                await tabs.close_page(page)
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                logger.debug("closing deviation page failed: %s", exc)

    async def preview(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> dict[str, dict[str, str | None]]:
        """
        Read every target's current SF value without writing anything.

        Dev-only: ``tools/smoke_submit.py --dry-run`` uses this to prove the page
        selectors and current values before the first real apply.
        """
        fields = self._fields.for_item(self._workflow, item.key)
        plans: list[_Plan] = []
        for spec in self._catalog:
            value = fields.get(spec.key)
            if value is None:
                continue
            intended = value.proposed or value.last_synced or value.extracted
            if intended is None:
                continue
            plans.append(
                _Plan(
                    spec,
                    _canonical(intended, spec.value_type) or intended,
                    False,
                )
            )
        if not plans:
            return {}
        groups = self._groups(item.key, plans)
        pages: dict[str, Page] = {}
        try:
            values = await self._read_all(
                groups, tabs, pages, log, "preview", self._timeouts.current()
            )
        finally:
            await self._close_pages(pages, tabs, "preview")
        result: dict[str, dict[str, str | None]] = {}
        for group in groups:
            result[group.kind] = {
                f"{target.label} [{target.section or ''}]": values.get(target)
                for target in group.targets
            }
        return result

    # -- planning ----------------------------------------------------------
    def _plans(self, item: WorkItem) -> list[_Plan]:
        """Turn non-empty proposed field values into canonical write plans.

        An empty or whitespace-only proposal means “no update” and is skipped, so a
        field the operator left blank is never sent to Salesforce (FR-5.6).
        """
        stored = self._fields.for_item(self._workflow, item.key)
        plans: list[_Plan] = []
        for spec in self._catalog:
            value = stored.get(spec.key)
            if (
                value is None
                or value.proposed is None
                or not value.proposed.strip()
            ):
                continue
            try:
                intended = normalise(value.proposed, spec.value_type)
            except ValueError as exc:
                raise _SubmitError(f"{spec.key}: invalid proposed value: {exc}") from exc
            applied = (
                value.applied is not None
                and _canonical(value.applied, spec.value_type) == intended
            )
            plans.append(_Plan(spec, intended, applied))
        return plans

    def _require_links(self, item_key: str) -> None:
        """
        Refuse to submit an item whose Salesforce links are not all usable.

        Runs before any status change or browser work. The message is the plain reason
        stored on the link ("Couldn't open the collateral list"), so the operator sees
        the same sentence the review card shows.
        """
        gap = incomplete_ref(
            self._ref_kinds, self._refs.for_item(self._workflow, item_key)
        )
        if gap is not None:
            raise _SubmitError(
                gap.reason or f"missing the {gap.kind.replace('_', ' ')} page link"
            )

    def _groups(self, item_key: str, plans: Sequence[_Plan]) -> list[_ObjectGroup]:
        """Group target values by object kind and attach the page refs."""
        refs = self._refs.for_item(self._workflow, item_key)
        by_kind: dict[str, dict[FieldTarget, str]] = {}
        for plan in plans:
            for target in plan.targets:
                if target.object_kind not in refs:
                    raise _SubmitError(
                        f"missing {target.object_kind} page link for {plan.field.key}"
                    )
                by_kind.setdefault(target.object_kind, {})[target] = plan.intended
        return [
            _ObjectGroup(kind, refs[kind], values)
            for kind, values in by_kind.items()
        ]

    def _begin(self, item: WorkItem) -> WorkItem:
        """Move the item into the submission phase, or accept an in-flight retry."""
        if item.status in _ENTERABLE_SUBMIT_STATUSES:
            return self._items.transition(
                self._workflow, item.key, WorkItemStatus.SUBMITTING
            )
        if item.status in _WORKING_SUBMIT_STATUSES:
            return item
        raise _SubmitError(f"cannot submit from status {item.status.value}")

    # -- browser work ------------------------------------------------------
    async def _close_pages(
        self, pages: dict[str, Page], tabs: TabProvider, what: str
    ) -> None:
        """
        Close every cached object page and forget it.

        Used between the apply and read-back stages (so validation re-opens each page
        instead of re-reading the DOM the writes just mutated) and from every cleanup
        ``finally``. Closing is best-effort: a page that is already gone must never mask
        the job's real error. The caller owns ``pages``; the dict is always emptied.
        """
        for page in pages.values():
            try:
                await tabs.close_page(page)
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                logger.debug("closing %s page failed: %s", what, exc)
        pages.clear()

    async def _read_all(
        self,
        groups: Sequence[_ObjectGroup],
        tabs: TabProvider,
        pages: dict[str, Page],
        log: JobLogger,
        stage: str,
        timeouts: SubmissionTimeouts,
    ) -> dict[FieldTarget, str | None]:
        """Read every target, opening each object page once and keeping it open.

        A page that dies during its own read aborts the stage with
        :class:`TransientBrowserError` rather than trusting the ``None`` values the
        dead tab produced: those would look like fields that failed to render. A read
        that merely overruns its budget is recorded as ``None`` for that object and the
        remaining objects are still read: during precheck that value is audit data, and
        during read-back the mismatch fails the item honestly.
        """
        values: dict[FieldTarget, str | None] = {}
        for group in groups:
            adapter = self._adapters.get(group.kind)
            page = pages.get(group.kind)
            if page is None:
                log(f"{stage}: {group.kind}: opening page")
                page = await adapter.open(tabs, group.ref)
                pages[group.kind] = page
            names = ", ".join(describe_target(target) for target in group.targets)
            log(f"{stage}: reading {group.kind} ({len(group.targets)} target(s)): {names}")
            started = time.monotonic()
            try:
                async with asyncio.timeout(timeouts.stage_read_ms / 1000):
                    values.update(await adapter.read(page, group.targets, log))
            except TimeoutError:
                log(
                    f"{stage}: {group.kind}: read did not finish within "
                    f"{timeouts.stage_read_ms // 1000}s"
                )
                for target in group.targets:
                    values[target] = None
                continue
            if page_closed(page):
                log(f"{stage}: {group.kind}: page closed while reading")
                raise TransientBrowserError(f"{group.kind} page closed while reading")
            log(
                f"{stage}: {group.kind}: read done in "
                f"{time.monotonic() - started:.1f}s"
            )
        return values

    async def _write_all(
        self,
        groups: Sequence[_ObjectGroup],
        pages: Mapping[str, Page],
        current: Mapping[FieldTarget, str | None],
        plans: Sequence[_Plan],
        log: JobLogger,
        timeouts: SubmissionTimeouts,
    ) -> dict[FieldTarget, WriteOutcome]:
        """Write targets that are not already applied, object by object.

        A target page that has already died aborts the stage with
        :class:`TransientBrowserError`; continuing would write through a browser that
        lost a tab, and the worker's retry re-reads the current values before writing
        again.

        A group that overruns its budget is a different fault: the tab is alive, so the
        remaining groups are still written (this pipeline never retries a submission, so
        every group that lands is manual work saved) and only the overrun group is
        recorded ``UNKNOWN``, because its partial writes cannot be confirmed.
        """
        target_plan = {target: plan for plan in plans for target in plan.targets}
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        for group in groups:
            values: dict[FieldTarget, str] = {}
            for target, intended in group.values.items():
                plan = target_plan[target]
                if (
                    _canonical(current.get(target), plan.field.value_type)
                    == plan.intended
                ):
                    # The page already holds the proposed value, so there is nothing
                    # to write: a retry after a crash must not write it twice
                    # (FR-6.8), and an SF form can leave a modification to an equal
                    # value unconfirmed, which would fail the item over a no-op.
                    outcomes[target] = WriteOutcome.SAVED
                    log(
                        f"apply: {group.kind}: {describe_target(target)} already "
                        f"at {plan.intended}; no write needed"
                    )
                    continue
                values[target] = intended
            if not values:
                log(f"apply: {group.kind}: already applied; no write needed")
                continue
            if page_closed(pages[group.kind]):
                log(f"apply: {group.kind}: page closed; aborting the submission")
                raise TransientBrowserError(f"{group.kind} page closed before apply")
            log(f"apply: {group.kind} ({len(values)} target(s))")
            adapter: ObjectAdapter = self._adapters.get(group.kind)
            started = time.monotonic()
            try:
                async with asyncio.timeout(timeouts.stage_write_ms / 1000):
                    outcomes.update(
                        await adapter.write(pages[group.kind], values, log)
                    )
            except TimeoutError:
                log(
                    f"apply: {group.kind}: write did not finish within "
                    f"{timeouts.stage_write_ms // 1000}s"
                )
                for target in values:
                    outcomes[target] = WriteOutcome.UNKNOWN
                continue
            log(
                f"apply: {group.kind}: done in "
                f"{time.monotonic() - started:.1f}s"
            )
            if page_closed(pages[group.kind]):
                # The tab died while its own targets were being written: the outcomes
                # above were produced by a page that no longer exists, so they cannot
                # be trusted or recorded as rejections.
                log(f"apply: {group.kind}: page closed during the write")
                raise TransientBrowserError(f"{group.kind} page closed during the write")
        return outcomes

    # -- checks ------------------------------------------------------------
    def _audit_precheck(
        self,
        item: WorkItem,
        groups: Sequence[_ObjectGroup],
        current: Mapping[FieldTarget, str | None],
        log: JobLogger,
    ) -> None:
        """
        Record the current SF values before the first write.

        This is audit data and the input to the idempotency check; it is deliberately
        **not** a gate. A value that differs from the last watcher snapshot does not
        block the write, because the description-derived snapshot is not guaranteed to
        be true. The operator's proposal is authoritative.
        """
        lines: list[str] = []
        for group in groups:
            pairs = ", ".join(
                f"{target.label} [{target.section or ''}]={current.get(target)!r}"
                for target in group.targets
            )
            line = f"{group.kind}: {pairs}"
            lines.append(line)
            log(f"precheck: {line}")
        self._events.emit(
            "submit_precheck",
            workflow=self._workflow,
            item=item.key,
            detail="; ".join(lines),
        )

    def _check_readback(
        self,
        item_key: str,
        plans: Sequence[_Plan],
        readback: Mapping[FieldTarget, str | None],
        log: JobLogger,
    ) -> None:
        """Every target must read back the intended canonical value."""
        for plan in plans:
            for target in plan.targets:
                seen = _canonical(readback.get(target), plan.field.value_type)
                if seen != plan.intended:
                    self._fields.mark_rejected(
                        self._workflow, item_key, plan.field.key
                    )
                    log(
                        f"readback mismatch: {plan.field.key}/"
                        f"{target.object_kind}: {readback.get(target)!r} "
                        f"!= {plan.intended!r}"
                    )
                    raise _SubmitError(
                        f"{plan.field.key}/{target.object_kind}: read-back "
                        f"{readback.get(target)!r} != {plan.intended!r}"
                    )
            log(f"validated: {plan.field.key}")

    def _record_apply(
        self,
        item_key: str,
        plans: Sequence[_Plan],
        outcomes: Mapping[FieldTarget, WriteOutcome],
        log: JobLogger,
    ) -> None:
        """Persist per-field truth: applied only when every target saved."""
        for plan in plans:
            results = [outcomes.get(target) for target in plan.targets]
            if results and all(result is WriteOutcome.SAVED for result in results):
                self._fields.mark_applied(
                    self._workflow, item_key, plan.field.key, plan.intended
                )
                log(f"applied: {plan.field.key}={plan.intended}")
            else:
                self._fields.mark_rejected(
                    self._workflow, item_key, plan.field.key
                )
                log(f"rejected: {plan.field.key}")

    def _already_closed(
        self, item: WorkItem, reason: str, log: JobLogger
    ) -> SubmitOutcome:
        """Record an absence-driven skip; the closure resolver writes CLOSED later."""
        self._events.emit(
            "submit_already_closed",
            workflow=self._workflow,
            item=item.key,
            detail=reason,
        )
        log(f"{item.key}: already closed — {reason}")
        return SubmitOutcome.ALREADY_CLOSED

    def _fail(self, item: WorkItem, reason: str, log: JobLogger) -> SubmitOutcome:
        """Move a mid-phase item to NEEDS_REVIEW and report a reviewable failure."""
        fresh = self._items.get(self._workflow, item.key)
        if fresh is not None and fresh.status in _WORKING_SUBMIT_STATUSES:
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
            "submit_failed",
            workflow=self._workflow,
            item=item.key,
            detail=reason,
        )
        log(f"{item.key}: submission failed — {reason}")
        return SubmitOutcome.FAILED
