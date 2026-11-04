"""Job logger: every line goes to the process log and to ``job_logs`` (FR-7.6)."""

from __future__ import annotations

import logging

from app.core.repo.jobs import JobRepository

_log = logging.getLogger(__name__)


class RepositoryLogger:
    """Job logger that mirrors every line to the database."""

    def __init__(self, job_id: int, jobs: JobRepository) -> None:
        """Bind to one job."""
        self._job_id = job_id
        self._jobs = jobs

    def __call__(self, message: str) -> None:
        """Record one line to the process log and the job log."""
        _log.info("[job %s] %s", self._job_id, message)
        self._jobs.log(self._job_id, message)
