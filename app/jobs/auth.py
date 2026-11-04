"""Job execution: wake/sleep policy for authentication, workers, dispatch."""

from __future__ import annotations

import asyncio

from app.core.models import Job
from app.core.repo.events import EventRepository
from app.core.repo.jobs import JobRepository


class AuthGate:
    """
    Single policy for "Salesforce needs a manual login".

    While paused, no job is claimed and in-flight work is parked instead of failed
    (FR-1.4, FR-7.8). ``wait()`` is what the dispatcher and watcher block on.

    Example:
        await auth.wait()      # returns immediately unless paused
        auth.pause("expired")
        await auth.wait()      # blocks until resume()
    """

    def __init__(self, jobs: JobRepository, events: EventRepository) -> None:
        """Start un-paused."""
        self._jobs = jobs
        self._events = events
        self._paused = False
        self._resumed = asyncio.Event()
        self._resumed.set()

    @property
    def paused(self) -> bool:
        """Whether claiming is currently suspended."""
        return self._paused

    async def wait(self) -> None:
        """Suspend the caller until authentication is available again."""
        await self._resumed.wait()

    def pause(self, reason: str) -> None:
        """Suspend claiming once; safe to call repeatedly."""
        if self._paused:
            return
        self._paused = True
        self._resumed.clear()
        self._events.emit("auth_paused", detail=reason)

    def resume(self) -> None:
        """Resume claiming after a fresh login."""
        if not self._paused:
            return
        self._paused = False
        self._resumed.set()
        self._events.emit("auth_resumed")

    def on_session_expired(self, job: Job) -> None:
        """
        Park the current job and stop claiming more until a login happens.

        Example:
            try:
                ...
            except SessionExpired:
                auth.on_session_expired(job)   # blocked_auth + paused
        """
        self._jobs.release_blocked(job.id)
        self.pause("session expired — manual login required")
