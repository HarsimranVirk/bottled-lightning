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
    RefState,
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

    Identity is ``(workflow, key)``; every field's own meaning is documented on the
    field, so this docstring only states the invariant: a row exists from first sighting
    until a closure, and history is kept per ``epoch`` rather than per row.
    """

    workflow: str
    """Owning workflow name, e.g. ``deviations_z02``; with ``key`` it identifies the row."""

    key: str
    """Workflow-assigned item key, e.g. ``Deviation-28102026-484106``; stable per epoch."""

    record_url: str | None
    """Lightning URL of the deviation record taken from the list row, so an EXTRACT job
    never needs the list snapshot; ``None`` until a valid refresh stored it."""

    status: WorkItemStatus
    """Current pipeline status; every transition and the repair pass reads it."""

    source: ClosureSource | None
    """Who closed the item (this system or Salesforce); ``None`` while the item is open."""

    reason: str | None
    """Operator-facing explanation of the last status change; ``None`` when there is none."""

    present: bool
    """Seen in the latest *valid* refresh; a closure flips it to ``False``."""

    epoch: int
    """Increments each time a closed item reappears, keeping earlier history attributable."""

    first_seen: datetime
    """UTC timestamp of the first refresh that listed the item."""

    last_seen: datetime
    """UTC timestamp of the most recent refresh that listed the item."""

    absent_since: datetime | None
    """UTC timestamp when the item first went missing from the list; ``None`` while present."""

    approved_at: str | None
    """Approval Date exactly as the printable view rendered it (not parsed); ``None`` when
    the list row had no approval date."""

    extracted_at: datetime | None
    """UTC timestamp of the one-shot detail extraction; ``None`` until it was visited."""

    execute_attempted_at: datetime | None
    """UTC timestamp of the final-action attempt; ``None`` if it was never attempted."""

    execute_confirmed_at: datetime | None
    """UTC timestamp Salesforce confirmed the final action; ``None`` until then."""

    closed_at: datetime | None
    """UTC timestamp the item reached a terminal state; ``None`` while it is still open."""


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
    """Owning workflow name, e.g. ``deviations_z02``."""

    key: str
    """Item key the decision applies to, e.g. ``Deviation-28102026-484106``."""

    decision: DecisionKind
    """The judgement recorded: accept, reject, or ``PENDING`` as the explicit undo."""

    reason: str | None
    """Free-text justification typed by the operator; ``None`` when they gave none."""

    created_at: datetime
    """UTC timestamp of the decision; the newest row per item is the current one."""


@dataclass(frozen=True, slots=True)
class ApprovedDeviation:
    """
    A point-in-time copy of an accepted deviation, kept outside the current tables.

    ``decided_at`` is the accept timestamp and the history sort key. The parent is
    written on accept and refreshed on submit/closure, while ``snapshot_at`` records the
    last refresh. Because the row lives in ``approved_deviations`` and has no foreign key
    to ``work_items``, purging current data cannot erase it.

    Example:
        approved = history.get("deviations_z02", key)
        if approved is not None:
            print(approved.key, approved.decided_at)
    """

    workflow: str
    """Owning workflow name, e.g. ``deviations_z02``."""

    key: str
    """Item key of the deviation this snapshot was taken from."""

    epoch: int
    """Epoch of the source item at accept time, so a re-appeared item is not confused
    with the snapshot."""

    status: WorkItemStatus
    """Item status frozen at accept time; later submits/closures refresh the parent row."""

    source: ClosureSource | None
    """Who closed the item, frozen with the snapshot; ``None`` if it was still open."""

    present: bool
    """Whether the item was in the list when the snapshot was taken."""

    record_url: str | None
    """Lightning URL of the deviation record, kept so history stays clickable; ``None`` if
    the item never had one."""

    approved_at: str | None
    """Approval Date exactly as the printable view rendered it; ``None`` when absent."""

    reason: str | None
    """Closure or status reason recorded at snapshot time; ``None`` when there was none."""

    decided_at: datetime
    """UTC timestamp of the accept decision; the history sort key."""

    decision_reason: str | None
    """Justification the operator gave when accepting; ``None`` when they gave none."""

    snapshot_at: datetime
    """UTC timestamp this copy was last refreshed (on accept, then submit and closure)."""


@dataclass(frozen=True, slots=True)
class FieldValue:
    """
    State of one editable value for one item.

    The four value slots are deliberately separate — see the attribute docstrings. They
    exist so a refresh can update ``extracted``/``last_synced`` without ever clobbering
    an operator's pending edit or losing what SF already accepted.

    Example progression for ``tenure``:
        extracted=240, proposed=None, applied=None        # just extracted
        extracted=240, proposed=300, applied=None         # operator edited
        extracted=240, proposed=300, applied="300"        # submit succeeded
    """

    workflow: str
    """Owning workflow name, e.g. ``deviations_z02``."""

    item: str
    """Item key the value belongs to, e.g. ``Deviation-28102026-484106``."""

    key: str
    """Catalogue key of the field, e.g. ``tenure`` or ``loan_amount``."""

    extracted: str | None
    """What extraction parsed, formatted for display (Indian-grouped amount, months for
    tenure); best-effort, so ``None`` when the page had nothing usable."""

    last_synced: str | None
    """What SF showed at the last refresh, in the same display format; ``None`` until a
    job read the page."""

    proposed: str | None
    """The operator's pending edit; a refresh must never overwrite it, and ``None`` means
    no edit is pending."""

    applied: str | None
    """What SF accepted when the edit was written; ``None`` until a submit succeeded."""

    status: FieldStatus
    """Where the value is in the edit lifecycle (extracted/proposed/applied/rejected)."""

    updated_at: datetime
    """UTC timestamp of the last write to any slot, used for audit and retention."""


@dataclass(frozen=True, slots=True)
class Attribute:
    """
    A read-only extracted value, shown for context.

    Attributes are the counterpart of :class:`FieldValue`: they are never edited
    or written back. Description, ROI values and product type live here, which is
    why adding a new read-only value needs no schema change.
    """

    workflow: str
    """Owning workflow name, e.g. ``deviations_z02``."""

    item: str
    """Item key the value belongs to, e.g. ``Deviation-28102026-484106``."""

    name: str
    """Attribute name as stored, e.g. ``description``, ``product_type`` or an ROI key;
    free-form so a new read-only value needs no schema change."""

    value: str | None
    """Extracted display text (never edited or written back); ``None`` when extraction
    found nothing for this name."""


@dataclass(frozen=True, slots=True)
class PageRef:
    """
    Link to one SF object involved in an item, plus how sure extraction is of it.

    ``state`` is ``FOUND`` for a usable link; ``ABSENT``/``UNRESOLVED`` rows carry an
    empty ``name``/``url`` because there is nothing to open, and a user-facing
    ``reason``. Extraction persists one row per expected object kind so a retry never
    has to guess whether a kind was fetched, found empty, or never resolved.
    """

    workflow: str
    """Owning workflow name, e.g. ``deviations_z02``; with ``item`` and ``kind`` it is the
    row key, so an item never holds two links to the same object kind."""

    item: str
    """Work-item key this link belongs to, stored as ``item_key`` in the table, e.g.
    ``Deviation-28102026-484106``."""

    kind: str
    """Which SF object this is: one of the workflow's declared ``RefKind`` values, e.g.
    ``opportunity`` or ``cl_contract``. Not free text — an undeclared kind is rejected."""

    name: str
    """The object's Salesforce identifier, shown as the link text, e.g. ``LAI-00533155``
    (CL contract) or ``CJID-0000280688`` (collateral); ``""`` when nothing was found."""

    url: str
    """Absolute Lightning URL of the object, openable headless with the stored session;
    ``""`` when ``state`` is not ``FOUND``, so callers must branch on ``state``."""

    state: RefState = RefState.FOUND
    """``FOUND`` (usable link), ``ABSENT`` (Salesforce says the object does not exist) or
    ``UNRESOLVED`` (the lookup did not finish) — see :class:`RefState`."""

    reason: str | None = None
    """Plain sentence for the operator when ``state`` is not ``FOUND``, e.g. "No
    collateral attached to this opportunity"; ``None`` for a found link."""


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

    Claiming is restart-safe through the lease pair plus the partial unique index that
    allows at most one active job per item; every field's meaning is on the field.
    """

    id: int
    """Database row id; the handle routes and the log use to address the job."""

    workflow: str
    """Owning workflow name, e.g. ``deviations_z02``."""

    kind: JobKind
    """Which pipeline runs: list refresh, extraction, submit, or final action."""

    item: str
    """Item key the job works on, e.g. ``Deviation-28102026-484106``."""

    status: JobStatus
    """Queue state (queued/running/done/failed/cancelled); transitions are repository-only."""

    phase: Phase | None
    """How far a submission got before it stopped; ``None`` for non-submit jobs or one that
    never advanced."""

    attempts: int
    """Lease claims so far; an expired lease requeues the job and increments this."""

    lease_owner: str | None
    """Identity of the worker holding the job; ``None`` when nobody holds it."""

    lease_expires_at: datetime | None
    """UTC time the claim expires; after it, another worker may requeue and re-claim.
    ``None`` when the job is not leased."""

    created_at: datetime
    """UTC timestamp the job was enqueued."""

    started_at: datetime | None
    """UTC timestamp of the first claim; ``None`` for a job that never started."""

    finished_at: datetime | None
    """UTC timestamp the job reached a terminal state; ``None`` while it is still running."""

    error: str | None
    """Last failure message shown to the operator; ``None`` when the job has not failed."""


@dataclass(frozen=True, slots=True)
class SyncRun:
    """
    One refresh of one workflow's list view.

    Invalid runs are recorded too (FR-2.4): ``valid`` is False and ``warning``
    carries the header/rows mismatch, which is how a silently broken extraction
    becomes visible instead of looking like an empty list.
    """

    id: int
    """Database row id; the ``sync_runs`` ring keeps only the newest 20 per workflow."""

    workflow: str
    """Owning workflow name, e.g. ``deviations_z02``."""

    captured_at: datetime
    """UTC timestamp the refresh finished and its counts were recorded."""

    header_total: int | None
    """The "N items" total the list header displayed, used for the cross-check; ``None``
    when the header never rendered, which is itself a warning sign."""

    rows_read: int
    """Rows the extractor actually parsed from the printable view."""

    valid: bool
    """True only when ``header_total`` was read and equals ``rows_read``; a mismatch keeps
    the refresh's rows out of the item table."""

    warning: str | None
    """Human-readable reason the run is not valid, e.g. "header total 42 != rows 40";
    ``None`` for a valid run."""

    added: int
    """Items first seen in this refresh."""

    updated: int
    """Existing items whose listed fields changed in this refresh."""

    closed: int
    """Items this refresh closed because they no longer appeared in the list."""


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """
    Persisted Playwright storage state, kept as opaque JSON text.

    The snapshot is as sensitive as the account password: it is never logged and
    never returned by the API. ``cookie_count`` exists so the UI can show whether a
    login actually produced cookies.
    """

    storage_state: str
    """Playwright ``storage_state()`` JSON, kept verbatim so it can be handed straight to
    ``ctx.add_cookies``; never logged and never returned by the API."""

    cookie_count: int
    """How many cookies the snapshot holds, so the UI can show whether a login actually
    produced any instead of failing silently later."""

    created_at: datetime
    """UTC timestamp the snapshot was captured (right after a manual login)."""

    org: str | None
    """Base org URL the snapshot was captured against, used to reject a snapshot taken on
    a different org; ``None`` for snapshots saved before this column existed."""
