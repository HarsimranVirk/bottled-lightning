"""List-view watcher: one on-demand page per workflow (FR-2.1, FR-2.2).

The watcher is the clock of the system. Every ``refresh_interval_s`` it opens the
workflow's list page when needed, samples it and hands the sample to the reconciler.
It never interprets the sample itself, never writes item status, and never runs a job.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Protocol

from app.config import Settings
from app.core.errors import SessionExpired
from app.core.list_view import ListSample, ListViewSpec
from app.core.models import SyncRun
from app.core.repo.events import EventRepository
from app.core.workflow import Workflow
from app.jobs.auth import AuthGate
from app.salesforce.list_page import ListPage
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider

from .reconciler import Reconciler

logger = logging.getLogger(__name__)


class SampleSource(Protocol):
    """Where the watcher gets list samples: a real Lightning page or a test fake."""

    async def ensure_open(self) -> None:
        """Make the source ready to sample, opening it once if needed (idempotent).

        Called on the browser loop inside the watcher's cycle lock, so two cycles
        cannot race to open a page. Raises ``SessionExpired`` when the stored
        session cannot authenticate.
        """
        ...

    async def sample(self) -> ListSample:
        """Return one fresh sample; only valid after ``ensure_open()`` in this cycle."""
        ...

    async def close(self) -> None:
        """Drop any page held by the source; safe when it is already closed."""
        ...


class WorkflowListSource:
    """Production sample source: one dedicated page on the workflow's list view.

    The page is created on demand and kept between cycles, which is what makes a 30 s
    cadence cheap — Lightning is not re-navigated from scratch each time. After an
    authentication failure the page is dropped, so the next cycle opens exactly one
    fresh page (FR-2.1, FR-2.11).
    """

    def __init__(
        self,
        runtime: BrowserRuntime,
        workflow: Workflow,
        settings: Settings,
        session: SessionProvider,
    ) -> None:
        """Hold the runtime, workflow, settings and session provider; open nothing yet."""
        self._runtime = runtime
        self._workflow = workflow
        self._settings = settings
        self._session = session
        self._list: ListPage | None = None

    async def ensure_open(self) -> None:
        """Open the list page unless it is already open (idempotent).

        Runs on the browser loop inside the watcher's cycle lock, so the periodic
        cycle and a manual refresh cannot create a second page (FR-2.10). Raises
        ``SessionExpired`` when the stored session cannot authenticate; the page is
        closed before re-raising so the next attempt starts clean.
        """
        if self._list is not None:
            return
        context = self._runtime.context
        page = await context.new_page()
        try:
            await self._session.ensure(page)
            spec = ListViewSpec(
                url=self._workflow.list_view.url,
                pattern=self._workflow.list_view.pattern,
            )
            list_page = ListPage(
                context, page, spec, self._settings.timeouts
            )
            await list_page.open()
        except BaseException:
            with suppress(Exception):
                await page.close()
            raise
        self._list = list_page

    async def sample(self) -> ListSample:
        """Refresh the open page and read a sample.

        Must be called after ``ensure_open()`` in the same serialised cycle. The
        ``RuntimeError`` below is a programmer-error guard, not an auth signal: an
        expired session surfaces from ``ensure()`` as ``SessionExpired``.
        """
        list_page = self._list
        if list_page is None:
            raise RuntimeError("WorkflowListSource.sample() requires ensure_open()")
        await self._session.ensure(list_page.page)
        await list_page.refresh()
        return await list_page.read()

    async def close(self) -> None:
        """Close the page if one is open; safe to call repeatedly."""
        list_page = self._list
        self._list = None
        if list_page is not None:
            await list_page.close()


class ListWatcher:
    """One workflow's refresh clock: sample the list view, hand it to the reconciler.

    The page is opened by a cycle rather than at start-up, and every cycle runs under
    one lock, so a manual refresh and the periodic loop can never open two pages or
    read one page concurrently (FR-2.1, FR-2.10). The watcher never runs jobs and
    never writes terminal status.
    """

    def __init__(
        self,
        workflow: Workflow,
        source: SampleSource,
        reconciler: Reconciler,
        events: EventRepository,
        auth: AuthGate,
        interval_s: float,
    ) -> None:
        """Wire one workflow's cycle; nothing touches the browser until ``run_forever``."""
        self._workflow = workflow
        self._source = source
        self._reconciler = reconciler
        self._events = events
        self._auth = auth
        self._interval_s = interval_s
        # Serialises ensure-open + sample between the periodic cycle and a manual
        # refresh. Created off-loop but only ever acquired on the browser loop.
        self._lock = asyncio.Lock()

    async def run_forever(self) -> None:
        """Refresh forever, pausing whenever authentication needs a human.

        Started once per registered workflow via ``BrowserRuntime.spawn``. The page
        is opened by the first cycle, not here, so an expired session at start-up
        pauses the gate instead of killing the task (FR-2.11). A non-auth failure is
        logged, emitted as ``sync_failed`` and retried after one interval (FR-2.12);
        only ``SessionExpired`` pauses the whole system.
        """
        try:
            while True:
                await self._auth.wait()
                try:
                    run = await self.refresh_once()
                    logger.info(
                        "sync %s: %s rows valid=%s +%s ~%s -%s",
                        run.workflow,
                        run.rows_read,
                        run.valid,
                        run.added,
                        run.updated,
                        run.closed,
                    )
                except SessionExpired as exc:
                    await self._discard_page()
                    self._auth.pause(f"watcher: {exc}")
                    continue
                except Exception:
                    logger.exception("watcher cycle failed for %s", self._workflow.name)
                    self._events.emit(
                        "sync_failed", workflow=self._workflow.name, detail="see logs"
                    )
                await asyncio.sleep(self._interval_s)
        finally:
            await self._discard_page()

    async def refresh_once(self) -> SyncRun:
        """Open the page if needed, sample once and reconcile.

        Used by the periodic loop and by a manual refresh; the lock keeps the two
        from opening two pages or reading one page concurrently (FR-2.10). It never
        waits on the auth gate and never retries: an expired session raises
        ``SessionExpired`` so the caller can pause the system (FR-2.13).
        """
        async with self._lock:
            await self._source.ensure_open()
            return self._reconciler.apply(await self._source.sample())

    async def _discard_page(self) -> None:
        """Close the source's page under the cycle lock.

        Taking the lock means a manual refresh that is mid-cycle is never torn down
        underneath; the close is idempotent, so a second failure is harmless.
        """
        async with self._lock:
            await self._source.close()
