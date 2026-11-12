"""The per-job progress log seam.

Kept in a leaf module so both ``app/core`` and ``app/salesforce`` can depend on it
without an import cycle. ``app.core.workflow`` re-exports it for existing callers.
"""

from __future__ import annotations

from typing import Protocol


class JobLogger(Protocol):
    """
    Callable that records one job progress line.

    Implemented in production by ``app.jobs.logger.RepositoryLogger``, which writes each
    line to the process log and to ``job_logs``. Adapters and pipelines receive it as an
    argument, so a job's browser work names its object, field and step in the persisted
    log (FR-7.13).
    """

    def __call__(self, message: str) -> None:
        """Append one line to the job log."""
        ...
