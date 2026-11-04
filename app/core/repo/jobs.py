"""Job queue: enqueue, claim with a lease, complete/fail, stale recovery."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from app.core.models import Job, to_iso, utcnow
from app.core.status import JobKind, JobStatus, Phase
from app.db.connection import Database

from ._util import opt_str, opt_time

_COLUMNS = (
    "id, workflow, item_key, kind, status, phase, attempts, lease_owner, "
    "lease_expires_at, created_at, started_at, finished_at, error"
)

#: Seconds between start and finish (or now while running). Derived, never stored.
_DURATION = (
    "(julianday(COALESCE(finished_at, 'now')) - julianday(started_at)) * 86400.0"
)

#: Public sort keys mapped to SQL; anything else is a validation error.
JOB_SORT_COLUMNS: dict[str, str] = {
    "id": "id",
    "status": "status",
    "kind": "kind",
    "phase": "phase",
    "item": "item_key",
    "created": "created_at",
    "started": "started_at",
    "finished": "finished_at",
    "duration": _DURATION,
    "attempts": "attempts",
    "error": "error",
}


@dataclass(frozen=True, slots=True)
class JobQuery:
    """Filters, sort and page window for the jobs table.

    Every filter is optional and composes with the others (FR-7.10). ``job_id`` and
    ``item``/``error`` are substring matches; the enums and dates are exact; the
    duration bounds are milliseconds. The service validates ``sort``/``order`` before
    constructing this, so the repository can map them straight to SQL.
    """

    workflow: str | None = None
    kind: JobKind | None = None
    status: JobStatus | None = None
    phase: Phase | None = None
    item: str | None = None
    job_id: str | None = None
    error: str | None = None
    started_after: str | None = None
    started_before: str | None = None
    duration_min_ms: int | None = None
    duration_max_ms: int | None = None
    sort: str = "id"
    order: str = "desc"
    limit: int = 25
    offset: int = 0


@dataclass(frozen=True, slots=True)
class JobPage:
    """One page of jobs plus the count of the whole filtered set."""

    jobs: list[Job]
    total: int


def _to_job(row: sqlite3.Row) -> Job:
    """Map a row to a ``Job``."""
    created = opt_time(row["created_at"])
    if created is None:
        raise ValueError("missing created_at")
    return Job(
        id=int(str(row["id"])),
        workflow=str(row["workflow"]),
        kind=JobKind(str(row["kind"])),
        item=str(row["item_key"]),
        status=JobStatus(str(row["status"])),
        phase=Phase(str(row["phase"])) if row["phase"] is not None else None,
        attempts=int(str(row["attempts"])),
        lease_owner=opt_str(row["lease_owner"]),
        lease_expires_at=opt_time(row["lease_expires_at"]),
        created_at=created,
        started_at=opt_time(row["started_at"]),
        finished_at=opt_time(row["finished_at"]),
        error=opt_str(row["error"]),
    )


class JobRepository:
    """
    Persistent job queue: enqueue, lease, complete, fail, recover.

    Leases make claiming safe without a lock: ``claim`` moves one queued row to
    ``RUNNING`` with an expiry, ``heartbeat`` extends it, and ``requeue_stale``
    returns expired leases to the queue after a crash.
    """

    def __init__(self, db: Database) -> None:
        """Bind to the database handle."""
        self._db = db

    # -- queue -------------------------------------------------------------
    def enqueue(self, workflow: str, kind: JobKind, key: str) -> Job:
        """
        Create a queued job, or return the item's already-active job.

        Deduplication is enforced by the ``jobs_active`` partial unique index, not by a
        read-then-write check, so two callers racing cannot create two active jobs
        (invariant I2).

        Example:
            job = jobs.enqueue(workflow, JobKind.EXTRACT, key)   # queued
            jobs.enqueue(workflow, JobKind.EXTRACT, key)         # returns the same job
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO jobs (workflow, item_key, kind, status, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [workflow, key, kind.value, JobStatus.QUEUED.value, to_iso(utcnow())],
                )
                job_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            existing = self.active_for(workflow, key)
            if existing is None:
                raise
            return existing
        if job_id is None:
            raise LookupError("job insert returned no id")
        return self.require(int(job_id))

    def active_for(self, workflow: str, key: str) -> Job | None:
        """The item's active job, if any (invariant I2)."""
        row = (
            self._db.connect()
            .execute(
                f"SELECT {_COLUMNS} FROM jobs "
                "WHERE workflow = ? AND item_key = ? "
                "AND status IN ('queued', 'running', 'blocked_auth') "
                "ORDER BY id DESC LIMIT 1",
                [workflow, key],
            )
            .fetchone()
        )
        return None if row is None else _to_job(row)

    def claim(self, owner: str, ttl_s: float) -> Job | None:
        """
        Atomically take the oldest queued job and lease it to ``owner``.

        Implemented as a single ``UPDATE ... RETURNING`` so no other loop can claim the
        same row. Returns ``None`` when the queue is empty. ``attempts`` increments
        here, which is what the retry policy reads.
        """
        now = utcnow()
        expires = now + timedelta(seconds=ttl_s)
        with self._db.transaction() as conn:
            row = conn.execute(
                """
                UPDATE jobs
                   SET status = ?, lease_owner = ?, lease_expires_at = ?,
                       attempts = attempts + 1,
                       started_at = COALESCE(started_at, ?)
                 WHERE id = (
                       SELECT id FROM jobs WHERE status = ? ORDER BY id LIMIT 1
                 )
                RETURNING id
                """,
                [
                    JobStatus.RUNNING.value,
                    owner,
                    to_iso(expires),
                    to_iso(now),
                    JobStatus.QUEUED.value,
                ],
            ).fetchone()
        if row is None:
            return None
        return self.require(int(str(row[0])))

    def heartbeat(self, job_id: int, ttl_s: float) -> None:
        """Extend a running job's lease."""
        expires = utcnow() + timedelta(seconds=ttl_s)
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at = ? WHERE id = ? AND status = ?",
                [to_iso(expires), job_id, JobStatus.RUNNING.value],
            )

    def set_phase(self, job_id: int, phase: Phase) -> None:
        """Record which phase a job is executing."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET phase = ? WHERE id = ?", [phase.value, job_id]
            )

    def complete(self, job_id: int) -> None:
        """Mark a job succeeded and release its lease."""
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE jobs
                   SET status = ?, finished_at = ?, lease_owner = NULL,
                       lease_expires_at = NULL, error = NULL
                 WHERE id = ?
                """,
                [JobStatus.SUCCEEDED.value, to_iso(utcnow()), job_id],
            )

    def fail(self, job_id: int, error: str, *, retryable: bool = False) -> None:
        """
        Fail a job, or requeue it when the failure is retryable.

        ``retryable=True`` puts the row back in ``QUEUED`` (attempts already counted);
        otherwise it becomes ``FAILED`` with ``finished_at`` set and stays visible in
        the UI with its error.
        """
        now = to_iso(utcnow())
        with self._db.transaction() as conn:
            if retryable:
                conn.execute(
                    """
                    UPDATE jobs
                       SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                           error = ?
                     WHERE id = ?
                    """,
                    [JobStatus.QUEUED.value, error, job_id],
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                       SET status = ?, finished_at = ?, lease_owner = NULL,
                           lease_expires_at = NULL, error = ?
                     WHERE id = ?
                    """,
                    [JobStatus.FAILED.value, now, error, job_id],
                )

    def release_blocked(self, job_id: int) -> None:
        """
        Park a job until authentication is restored (session expired).

        The job keeps its active slot (the unique index still sees it) so nothing else
        can queue a duplicate for the same item while the operator logs in.
        """
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE jobs
                   SET status = ?, lease_owner = NULL, lease_expires_at = NULL
                 WHERE id = ?
                """,
                [JobStatus.BLOCKED_AUTH.value, job_id],
            )

    def cancel_active_for(self, workflow: str, key: str) -> int:
        """
        Cancel queued and blocked jobs for an item that has closed.

        Running jobs are not touched: they abort at their next safe boundary and the
        resolver applies the close when the lease is released (FR-6.11).
        """
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                   SET status = ?, finished_at = ?, lease_owner = NULL,
                       lease_expires_at = NULL
                 WHERE workflow = ? AND item_key = ?
                   AND status IN ('queued', 'blocked_auth')
                """,
                [JobStatus.CANCELLED.value, to_iso(utcnow()), workflow, key],
            )
        return cursor.rowcount

    def cancel(self, job_id: int) -> bool:
        """Cancel one queued job; returns whether it changed."""
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                   SET status = ?, finished_at = ?
                 WHERE id = ? AND status = ?
                """,
                [
                    JobStatus.CANCELLED.value,
                    to_iso(utcnow()),
                    job_id,
                    JobStatus.QUEUED.value,
                ],
            )
        return cursor.rowcount > 0

    def requeue_stale(self) -> int:
        """
        Return expired running leases to the queue.

        Called when the queue looks idle and at boot. A crashed worker leaves a lease
        behind; this is what makes the job runnable again without duplicating effects,
        because every phase is idempotent (FR-6.8).
        """
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                   SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                       error = 'lease expired; requeued'
                 WHERE status = ?
                   AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                """,
                [JobStatus.QUEUED.value, JobStatus.RUNNING.value, to_iso(utcnow())],
            )
        return cursor.rowcount

    def query(self, query: JobQuery) -> JobPage:
        """One filtered, sorted page of jobs plus the filtered total (FR-7.10).

        ``LIKE`` filters are substring matches; ``started_after``/``started_before`` are
        UTC dates compared on the stored ISO prefix; duration bounds are converted from
        milliseconds to the SQL expression's seconds. Null sort values always sort last.

        Raises:
            ValueError: unknown ``sort`` key or ``order`` (the service turns this into a
                422 before it reaches SQL).
        """
        sort_expression = JOB_SORT_COLUMNS.get(query.sort)
        if sort_expression is None:
            raise ValueError(f"unknown sort: {query.sort}")
        direction = query.order.upper()
        if direction not in {"ASC", "DESC"}:
            raise ValueError(f"unknown order: {query.order}")

        where: list[str] = []
        params: list[str | int | float] = []
        if query.workflow is not None:
            where.append("workflow = ?")
            params.append(query.workflow)
        if query.kind is not None:
            where.append("kind = ?")
            params.append(query.kind.value)
        if query.status is not None:
            where.append("status = ?")
            params.append(query.status.value)
        if query.phase is not None:
            where.append("phase = ?")
            params.append(query.phase.value)
        if query.item:
            where.append("item_key LIKE ?")
            params.append(f"%{query.item}%")
        if query.job_id:
            where.append("CAST(id AS TEXT) LIKE ?")
            params.append(f"%{query.job_id}%")
        if query.error:
            where.append("COALESCE(error, '') LIKE ?")
            params.append(f"%{query.error}%")
        if query.started_after:
            where.append("substr(started_at, 1, 10) >= ?")
            params.append(query.started_after)
        if query.started_before:
            where.append("substr(started_at, 1, 10) <= ?")
            params.append(query.started_before)
        if query.duration_min_ms is not None:
            where.append(f"{_DURATION} >= ?")
            params.append(query.duration_min_ms / 1000)
        if query.duration_max_ms is not None:
            where.append(f"{_DURATION} <= ?")
            params.append(query.duration_max_ms / 1000)

        clause = "" if not where else " WHERE " + " AND ".join(where)
        conn = self._db.connect()
        total_row = conn.execute(
            f"SELECT COUNT(*) FROM jobs{clause}", params
        ).fetchone()
        total = 0 if total_row is None else int(str(total_row[0]))
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM jobs{clause} "
            f"ORDER BY ({sort_expression} IS NULL) ASC, {sort_expression} {direction}, id DESC "
            "LIMIT ? OFFSET ?",
            [*params, query.limit, query.offset],
        ).fetchall()
        return JobPage(jobs=[_to_job(row) for row in rows], total=total)

    def get(self, job_id: int) -> Job | None:
        """One job, or ``None``."""
        row = (
            self._db.connect()
            .execute(f"SELECT {_COLUMNS} FROM jobs WHERE id = ?", [job_id])
            .fetchone()
        )
        return None if row is None else _to_job(row)

    def require(self, job_id: int) -> Job:
        """One job or raise ``LookupError``."""
        job = self.get(job_id)
        if job is None:
            raise LookupError(f"unknown job {job_id}")
        return job

    # -- logs --------------------------------------------------------------
    def log(self, job_id: int, line: str) -> None:
        """Append a log line to a job."""
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO job_logs (job_id, seq, line, at)
                VALUES (?, COALESCE((SELECT MAX(seq) + 1 FROM job_logs WHERE job_id = ?), 1),
                        ?, ?)
                """,
                [job_id, job_id, line, to_iso(utcnow())],
            )

    def logs(self, job_id: int, limit: int = 5000) -> list[str]:
        """Ordered log lines for a job."""
        rows = (
            self._db.connect()
            .execute(
                "SELECT line FROM job_logs WHERE job_id = ? ORDER BY seq LIMIT ?",
                [job_id, limit],
            )
            .fetchall()
        )
        return [str(row["line"]) for row in rows]

    def counts(self) -> dict[str, int]:
        """Job count per status."""
        rows = (
            self._db.connect()
            .execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
            .fetchall()
        )
        return {str(row["status"]): int(str(row["n"])) for row in rows}
