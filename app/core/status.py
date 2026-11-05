"""Shared vocabularies: item lifecycle, job lifecycle, phases, outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class WorkItemStatus(StrEnum):
    """
    Shared item lifecycle across every workflow.

    The happy path:

        PRESENT -> EXTRACTING -> READY -> EDITING -> SUBMITTING
                -> APPLYING -> VALIDATING -> EXECUTING -> COMPLETED

    Closure can happen from most states: ``CLOSED`` when SF removed the item
    (FR-2.6), ``SKIPPED`` when extraction hit ambiguity, and ``ABSENT_PENDING``
    when closure was observed while a job still holds the lease (FR-6.11). Terminal
    states are re-enterable only through ``PRESENT`` (a new presence epoch).
    """

    PRESENT = "present"
    EXTRACTING = "extracting"
    READY = "ready"
    EDITING = "editing"
    SUBMITTING = "submitting"
    APPLYING = "applying"
    VALIDATING = "validating"
    EXECUTING = "executing"
    ABSENT_PENDING = "absent_pending"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    CLOSED = "closed"
    SKIPPED = "skipped"


TERMINAL_STATUSES: frozenset[WorkItemStatus] = frozenset(
    {WorkItemStatus.COMPLETED, WorkItemStatus.CLOSED, WorkItemStatus.SKIPPED}
)

#: Terminal statuses that a running job must never write over another job's work.
#: ``SKIPPED`` is excluded: the extraction pipeline writes it from inside its own lease.
CLOSURE_STATUSES: frozenset[WorkItemStatus] = frozenset(
    {WorkItemStatus.COMPLETED, WorkItemStatus.CLOSED}
)


class DecisionKind(StrEnum):
    """
    The operator's review decision on an item.

    ``PENDING`` is not a decision the operator makes: it is the append-only undo marker.
    A reader always takes the newest row, so ``PENDING`` means "undecided" and keeps the
    previous decision in the audit trail (FR-10.3).
    """

    ACCEPT = "accept"
    REJECT = "reject"
    PENDING = "pending"


class DecisionFilter(StrEnum):
    """
    Filter values accepted by the item list.

    ``UNDECIDED`` means no decision row at all *or* a latest row that is
    ``DecisionKind.PENDING``. There is no "any" member: omitting the filter means any.
    """

    ACCEPT = "accept"
    REJECT = "reject"
    UNDECIDED = "undecided"


class JobKind(StrEnum):
    """
    What a job does: extract data or submit changes.

    ``EXTRACT`` runs the workflow's extraction pipeline; ``SUBMIT`` runs its
    submission pipeline. The workflow is carried separately on the job row.
    """

    EXTRACT = "extract"
    SUBMIT = "submit"


class JobStatus(StrEnum):
    """
    Job lifecycle, including the parked-on-auth state.

        QUEUED -> RUNNING -> SUCCEEDED
                          -> FAILED
        RUNNING -> BLOCKED_AUTH   (session expired; resumes after a login)
        QUEUED  -> CANCELLED      (item closed before it ran)
    """

    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED_AUTH = "blocked_auth"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.BLOCKED_AUTH}
)


class Phase(StrEnum):
    """
    Ordered stage a job is executing; submission uses all four.

    Extraction jobs only use ``EXTRACT``. Submission walks ``APPLY`` -> ``VALIDATE``
    -> ``EXECUTE`` and persists each step so a crash can be reasoned about.
    """

    EXTRACT = "extract"
    APPLY = "apply"
    VALIDATE = "validate"
    EXECUTE = "execute"


class ClosureSource(StrEnum):
    """
    Who caused a closure: this system or Salesforce.

    ``SYSTEM`` means our final action was clicked (and, when observed, confirmed).
    ``EXTERNAL`` means the item left the list without us implementing it — the
    distinction FR-2.8 requires, derived from our own action record rather than from
    SF's modified-by field.
    """

    SYSTEM = "system"
    EXTERNAL = "external"


class FieldStatus(StrEnum):
    """
    Lifecycle of one editable value.

        EXTRACTED -> PROPOSED -> APPLIED
        EXTRACTED -> REJECTED          (SF refused a write)
    """

    EXTRACTED = "extracted"
    PROPOSED = "proposed"
    APPLIED = "applied"
    REJECTED = "rejected"


class WriteOutcome(StrEnum):
    """
    Per-field result of a write attempt.

    ``UNKNOWN`` exists because a click can succeed while the page dies before the
    result is read; callers treat it as neither success nor failure.
    """

    SAVED = "saved"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ExtractOutcome(StrEnum):
    """
    Pipeline result for an extraction job.

    ``EXTRACTED`` — data (or the fact that it was already extracted) is stored.
    ``SKIPPED`` — ambiguity or missing data; terminal, with a reason on the item.
    ``FAILED`` — retryable; the worker may requeue once.
    """

    EXTRACTED = "extracted"
    SKIPPED = "skipped"
    FAILED = "failed"


class SubmitOutcome(StrEnum):
    """
    Pipeline result for a submission job.

    ``COMPLETED`` — our final action ran (the workflow's word for it, e.g.
    "Implemented"). ``VALIDATED`` — apply and read-back succeeded, but the final
    action is intentionally disabled (Phase 6 bring-up); the item returns to
    ``READY`` so the operator can inspect the live values. ``ALREADY_CLOSED`` — the
    item was gone before we acted, which is a clean terminal outcome, not an error.
    ``FAILED`` — needs a human; never retried automatically.
    """

    COMPLETED = "completed"
    VALIDATED = "validated"
    ALREADY_CLOSED = "already_closed"
    FAILED = "failed"


S = WorkItemStatus

_TRANSITIONS: Mapping[WorkItemStatus, frozenset[WorkItemStatus]] = {
    S.PRESENT: frozenset(
        {S.EXTRACTING, S.READY, S.SKIPPED, S.CLOSED, S.ABSENT_PENDING}
    ),
    S.EXTRACTING: frozenset(
        {S.READY, S.SKIPPED, S.PRESENT, S.CLOSED, S.ABSENT_PENDING}
    ),
    S.READY: frozenset(
        {
            S.EDITING,
            S.SUBMITTING,
            S.EXTRACTING,
            S.NEEDS_REVIEW,
            S.CLOSED,
            S.ABSENT_PENDING,
        }
    ),
    S.EDITING: frozenset(
        {S.READY, S.SUBMITTING, S.NEEDS_REVIEW, S.CLOSED, S.ABSENT_PENDING}
    ),
    S.SUBMITTING: frozenset(
        {S.APPLYING, S.READY, S.NEEDS_REVIEW, S.CLOSED, S.ABSENT_PENDING}
    ),
    S.APPLYING: frozenset(
        {S.VALIDATING, S.READY, S.NEEDS_REVIEW, S.CLOSED, S.ABSENT_PENDING}
    ),
    S.VALIDATING: frozenset(
        {S.EXECUTING, S.READY, S.NEEDS_REVIEW, S.CLOSED, S.ABSENT_PENDING}
    ),
    S.EXECUTING: frozenset({S.COMPLETED, S.READY, S.NEEDS_REVIEW, S.ABSENT_PENDING}),
    S.ABSENT_PENDING: frozenset({S.COMPLETED, S.CLOSED}),
    S.NEEDS_REVIEW: frozenset(
        {S.READY, S.SUBMITTING, S.ABSENT_PENDING, S.CLOSED}
    ),
    S.COMPLETED: frozenset({S.PRESENT}),
    S.CLOSED: frozenset({S.PRESENT}),
    S.SKIPPED: frozenset({S.PRESENT}),
}


def can_transition(current: WorkItemStatus, target: WorkItemStatus) -> bool:
    """
    Whether the lifecycle allows ``current -> target``.

    A no-op transition is always allowed (idempotent writes). The rules are
    intentionally strict: execution cannot be reached without validation, and a
    terminal state can only be re-entered through ``PRESENT``.

    Example:
        >>> can_transition(WorkItemStatus.VALIDATING, WorkItemStatus.EXECUTING)
        True
        >>> can_transition(WorkItemStatus.VALIDATING, WorkItemStatus.COMPLETED)
        False
    """
    if current is target:
        return True
    return target in _TRANSITIONS[current]
