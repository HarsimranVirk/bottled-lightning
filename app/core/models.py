"""Domain entities. Frozen and passive: state changes happen through repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .status import (
    ClosureSource,
    DecisionKind,
    FieldStatus,
    JobKind,
    JobStatus,
    Phase,
    WorkItemStatus,
)


def utcnow() -> datetime:
    """Timezone-aware current time; every stored timestamp uses it."""
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    """Serialise a timestamp for SQLite."""
    return value.isoformat()


def from_iso(value: str | None) -> datetime | None:
    """Parse a stored timestamp, or ``None``."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class WorkItem:
    """
    One row of a workflow's list view, across its whole lifecycle.

    Identity is ``(workflow, key)``. Notes on the squishier fields:

    * ``present`` — seen in the latest *valid* refresh; a closure flips it to False
    * ``epoch`` — increments each time an item returns after a closure, so history
      stays attributable
    * ``source``/``reason``/``closed_at`` — set when the item reaches a terminal
      state; ``source`` says whether this system or SF closed it
    * ``execute_attempted_at`` / ``execute_confirmed_at`` — the final-action audit
      trail that makes FR-2.8 attribution answerable instead of guessed
    * ``record_url`` — taken from the list row so an EXTRACT job never needs the
      list snapshot to start
    """

    workflow: str
    key: str
    record_url: str | None
    status: WorkItemStatus
    source: ClosureSource | None
    reason: str | None
    present: bool
    epoch: int
    first_seen: datetime
    last_seen: datetime
    absent_since: datetime | None
    approved_at: str | None
    extracted_at: datetime | None
    execute_attempted_at: datetime | None
    execute_confirmed_at: datetime | None
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class Decision:
    """
    One row of the review-decision audit trail.

    Decisions are append-only: the newest row for ``(workflow, key)`` is the current
    decision, and ``DecisionKind.PENDING`` is the explicit undo that puts the item back
    in the deck without deleting history (FR-10.3). A decision is a review judgement,
    not a pipeline transition — it never changes ``WorkItem.status``.

    Example:
        accepted = Decision("deviations_z02", "Deviation-…", DecisionKind.ACCEPT,
                            None, utcnow())
    """

    workflow: str
    key: str
    decision: DecisionKind
    reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FieldValue:
    """
    State of one editable value for one item.

    The four value slots are deliberately separate:

    * ``extracted`` — what extraction parsed (may be None; best-effort)
    * ``last_synced`` — what SF showed at the last refresh
    * ``proposed`` — the operator's pending edit; a refresh must never overwrite it
    * ``applied`` — what SF accepted when the edit was written

    Example progression for ``tenure``:
        extracted=240, proposed=None, applied=None        # just extracted
        extracted=240, proposed=300, applied=None         # operator edited
        extracted=240, proposed=300, applied="300"        # submit succeeded
    """

    workflow: str
    item: str
    key: str
    extracted: str | None
    last_synced: str | None
    proposed: str | None
    applied: str | None
    status: FieldStatus
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Attribute:
    """
    A read-only extracted value, shown for context.

    Attributes are the counterpart of :class:`FieldValue`: they are never edited
    or written back. Description, ROI values and product type live here, which is
    why adding a new read-only value needs no schema change.
    """

    workflow: str
    item: str
    name: str
    value: str | None


@dataclass(frozen=True, slots=True)
class PageRef:
    """Link to one SF object involved in an item."""

    workflow: str
    item: str
    kind: str
    name: str
    url: str


def job_duration_ms(job: Job, at: datetime) -> int | None:
    """Elapsed milliseconds from ``started_at`` to ``finished_at`` (or ``at``).

    ``None`` for a job that never started (queued/cancelled). A running job's duration
    grows with ``at``, so the API reports live elapsed time without storing a second
    source of truth (FR-7.9).
    """
    if job.started_at is None:
        return None
    end = job.finished_at if job.finished_at is not None else at
    return max(0, int((end - job.started_at).total_seconds() * 1000))


@dataclass(frozen=True, slots=True)
class Job:
    """
    One unit of queued work for one item.

    ``kind`` decides which pipeline runs; ``phase`` records how far a submission
    got. The lease fields (``lease_owner``, ``lease_expires_at``) make claiming
    safe across restarts: a running job whose lease expires is requeued, and the
    partial unique index guarantees at most one active job per item.
    """

    id: int
    workflow: str
    kind: JobKind
    item: str
    status: JobStatus
    phase: Phase | None
    attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


@dataclass(frozen=True, slots=True)
class SyncRun:
    """
    One refresh of one workflow's list view.

    Invalid runs are recorded too (FR-2.4): ``valid`` is False and ``warning``
    carries the header/rows mismatch, which is how a silently broken extraction
    becomes visible instead of looking like an empty list.
    """

    id: int
    workflow: str
    captured_at: datetime
    header_total: int | None
    rows_read: int
    valid: bool
    warning: str | None
    added: int
    updated: int
    closed: int


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """
    Persisted Playwright storage state, kept as opaque JSON text.

    The snapshot is as sensitive as the account password: it is never logged and
    never returned by the API. ``cookie_count`` exists so the UI can show whether a
    login actually produced cookies.
    """

    storage_state: str
    cookie_count: int
    created_at: datetime
    org: str | None
