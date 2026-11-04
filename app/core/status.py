"""Shared vocabularies: item lifecycle, job lifecycle, phases, outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class WorkItemStatus(StrEnum):
    """Shared item lifecycle across every workflow."""

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


class JobKind(StrEnum):
    """What a job does: extract data or submit changes."""

    EXTRACT = "extract"
    SUBMIT = "submit"


class JobStatus(StrEnum):
    """Job lifecycle, including the parked-on-auth state."""

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
    """Ordered stage a job is executing; submission uses all four."""

    EXTRACT = "extract"
    APPLY = "apply"
    VALIDATE = "validate"
    EXECUTE = "execute"


class ClosureSource(StrEnum):
    """Who caused a closure: this system or Salesforce."""

    SYSTEM = "system"
    EXTERNAL = "external"


class FieldStatus(StrEnum):
    """Lifecycle of one editable value."""

    EXTRACTED = "extracted"
    PROPOSED = "proposed"
    APPLIED = "applied"
    REJECTED = "rejected"


class WriteOutcome(StrEnum):
    """Per-field result of a write attempt."""

    SAVED = "saved"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ExtractOutcome(StrEnum):
    """Pipeline result for an extraction job."""

    EXTRACTED = "extracted"
    SKIPPED = "skipped"
    FAILED = "failed"


class SubmitOutcome(StrEnum):
    """Pipeline result for a submission job."""

    COMPLETED = "completed"
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
    S.NEEDS_REVIEW: frozenset({S.READY, S.SUBMITTING, S.CLOSED}),
    S.COMPLETED: frozenset({S.PRESENT}),
    S.CLOSED: frozenset({S.PRESENT}),
    S.SKIPPED: frozenset({S.PRESENT}),
}


def can_transition(current: WorkItemStatus, target: WorkItemStatus) -> bool:
    """A no-op transition (same status) is always allowed; re-entry after a new presence
    epoch is allowed by the terminal statuses' rule."""
    if current is target:
        return True
    return target in _TRANSITIONS[current]
