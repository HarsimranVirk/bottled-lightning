"""Domain entities. Frozen and passive: state changes happen through repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .status import (
    ClosureSource,
    FieldStatus,
    JobKind,
    JobStatus,
    Phase,
    WorkItemStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    return value.isoformat()


def from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class WorkItem:
    """One row of a workflow's list view, across its whole lifecycle."""

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
class FieldValue:
    """Editable value state: what was scraped, what SF said last, what the operator wants,
    and what was actually written."""

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
    """Read-only extracted value shown for context (description, ROI, product type)."""

    workflow: str
    item: str
    name: str
    value: str | None


@dataclass(frozen=True, slots=True)
class PageRef:
    workflow: str
    item: str
    kind: str
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class Job:
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
    """One refresh of one workflow's list view."""

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
    """Persisted Playwright storage state, kept as opaque JSON text."""

    storage_state: str
    cookie_count: int
    created_at: datetime
    org: str | None
