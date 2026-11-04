"""Job queue: enqueue, claim with a lease, complete/fail, stale recovery."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from app.core.models import Job, to_iso, utcnow
from app.core.status import JobKind, JobStatus, Phase
from app.db.connection import Database

from ._util import opt_str, opt_time

_COLUMNS = (
    "id, workflow, item_key, kind, status, phase, attempts, lease_owner, "
    "lease_expires_at, created_at, started_at, finished_at, error"
)


def _to_job(row: sqlite3.Row) -> Job:
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
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- queue -------------------------------------------------------------
    def enqueue(self, workflow: str, kind: JobKind, key: str) -> Job:
        """Create a queued job. If one is already active for the item, return it.

        Invariant I2 (one active job per item) is enforced by the ``jobs_active`` partial
        unique index, so a race between two callers cannot create a duplicate.
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
        """Atomically take the oldest queued job and lease it to ``owner``."""
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
        expires = utcnow() + timedelta(seconds=ttl_s)
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at = ? WHERE id = ? AND status = ?",
                [to_iso(expires), job_id, JobStatus.RUNNING.value],
            )

    def set_phase(self, job_id: int, phase: Phase) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET phase = ? WHERE id = ?", [phase.value, job_id]
            )

    def complete(self, job_id: int) -> None:
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

    def query(
        self,
        workflow: str | None = None,
        kind: JobKind | None = None,
        status: JobStatus | None = None,
        limit: int = 100,
    ) -> list[Job]:
        where: list[str] = []
        params: list[object] = []
        if workflow is not None:
            where.append("workflow = ?")
            params.append(workflow)
        if kind is not None:
            where.append("kind = ?")
            params.append(kind.value)
        if status is not None:
            where.append("status = ?")
            params.append(status.value)
        clause = "" if not where else " WHERE " + " AND ".join(where)
        rows = (
            self._db.connect()
            .execute(
                f"SELECT {_COLUMNS} FROM jobs{clause} ORDER BY id DESC LIMIT ?",
                [*params, limit],
            )
            .fetchall()
        )
        return [_to_job(row) for row in rows]

    def get(self, job_id: int) -> Job | None:
        row = (
            self._db.connect()
            .execute(f"SELECT {_COLUMNS} FROM jobs WHERE id = ?", [job_id])
            .fetchone()
        )
        return None if row is None else _to_job(row)

    def require(self, job_id: int) -> Job:
        job = self.get(job_id)
        if job is None:
            raise LookupError(f"unknown job {job_id}")
        return job

    # -- logs --------------------------------------------------------------
    def log(self, job_id: int, line: str) -> None:
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
        rows = (
            self._db.connect()
            .execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
            .fetchall()
        )
        return {str(row["status"]): int(str(row["n"])) for row in rows}
