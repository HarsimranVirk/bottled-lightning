"""Claim loop: N concurrent workers, paused on authentication, stale leases recovered.

One asyncio task per concurrency slot; each loop claims one job at a time. Lowering the
worker count lets in-flight jobs finish (they are never cancelled mid-write, FR-7.7).
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import partial

from app.config import Settings
from app.core.repo.jobs import JobRepository

from .auth import AuthGate
from .worker import Worker

logger = logging.getLogger(__name__)


class Dispatcher:
    """
    Claims jobs and runs them on N slots; pauses on authentication.

    There is one asyncio task per slot and each claims one job at a time, so the
    worker count is the concurrency limit. When the gate is paused (expired
    session) no loop claims anything; lowering the count lets running jobs finish
    rather than cancelling them mid-write (FR-7.7).

    Example:
        dispatcher = Dispatcher(jobs, worker, auth, settings)
        task = asyncio.create_task(dispatcher.run_forever())
        ...
        dispatcher.stop()
        await task
    """

    def __init__(
        self,
        jobs: JobRepository,
        worker: Worker,
        auth: AuthGate,
        settings: Settings,
        *,
        poll_s: float = 2.0,
        lease_ttl_s: float = 300.0,
    ) -> None:
        """Wire queue, worker and gate; nothing starts until ``run_forever``."""
        self._jobs = jobs
        self._worker = worker
        self._auth = auth
        self._desired = settings.workers
        self._poll_s = poll_s
        self._lease_ttl_s = lease_ttl_s
        self._owner_prefix = f"{os.getpid()}"
        self._loops: dict[int, asyncio.Task[None]] = {}
        self._running = False

    @property
    def concurrency(self) -> int:
        """Desired number of concurrent slots."""
        return self._desired

    @property
    def in_flight(self) -> int:
        """Number of loop tasks currently alive."""
        return len(self._loops)

    async def run_forever(self) -> None:
        """
        Run claim loops until ``stop()``; cancels them on exit.

        Shutdown is deliberate: loops are cancelled only between jobs or while waiting
        on the auth gate. A lease that is abandoned this way is requeued by the next
        process.
        """
        self._running = True
        self._sync_loops()
        try:
            while self._running:
                await asyncio.sleep(1.0)
                self._sync_loops()
        finally:
            self._running = False
            for task in list(self._loops.values()):
                task.cancel()
            await asyncio.gather(*self._loops.values(), return_exceptions=True)
            self._loops.clear()

    def stop(self) -> None:
        """Ask the loops to finish; in-flight jobs are not interrupted."""
        self._running = False

    def set_concurrency(self, count: int) -> None:
        """
        Grow or shrink the pool; shrinking lets current jobs finish.

        Surplus slots notice the new limit before their next claim and exit, so no job
        is interrupted.
        """
        self._desired = max(1, count)
        self._sync_loops()

    def _sync_loops(self) -> None:
        """Spawn missing slots; surplus slots exit after their current job."""
        for index in range(self._desired):
            if index in self._loops:
                continue
            task = asyncio.create_task(self._loop(index), name=f"sf-job-{index}")
            self._loops[index] = task
            task.add_done_callback(partial(self._forget, index))

    def _forget(self, index: int, _task: asyncio.Task[None]) -> None:
        """Drop a finished loop from the registry."""
        self._loops.pop(index, None)

    async def _loop(self, index: int) -> None:
        """One slot: claim, execute, repeat until stopped or shrunk."""
        owner = f"{self._owner_prefix}:w{index}"
        while self._running and index < self._desired:
            await self._auth.wait()
            job = self._jobs.claim(owner, self._lease_ttl_s)
            if job is None:
                self._jobs.requeue_stale()
                await asyncio.sleep(self._poll_s)
                continue
            await self._worker.execute(job)
