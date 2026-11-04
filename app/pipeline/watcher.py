"""List-view watcher: one always-open page per workflow (FR-2.1, FR-2.2).

The watcher is the clock of the system. Every ``refresh_interval_s`` it samples the
workflow's list view and hands the sample to the reconciler. It never interprets the
sample itself, never writes item status, and never runs a job.
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
    async def open(self) -> None:
        """Acquire whatever the source needs before the first sample."""
        ...

    async def sample(self) -> ListSample:
        """Return one fresh sample of the list view."""
        ...

    async def close(self) -> None:
        """Release any page or browser resources held by the source."""
        ...


class WorkflowListSource:
    """Production sample source: one dedicated page on the workflow's list view.

    The page is opened once and refreshed per cycle, which is what makes a 30 s cadence
    cheap — Lightning is not re-navigated from scratch each time.
    """

    def __init__(
        self,
        runtime: BrowserRuntime,
        workflow: Workflow,
        settings: Settings,
        session: SessionProvider,
    ) -> None:
        self._runtime = runtime
        self._workflow = workflow
        self._settings = settings
        self._session = session
        self._list: ListPage | None = None

    async def open(self) -> None:
        """Open the list page and verify the session before the first read."""
        context = self._runtime.context
        page = await context.new_page()
        try:
            await self._session.ensure(page)
        except BaseException:
            with suppress(Exception):
                await page.close()
            raise
        spec = ListViewSpec(
            url=self._workflow.list_view.url,
            pattern=self._workflow.list_view.pattern,
        )
        list_page = ListPage(
            context, page, spec, self._settings.request_timeout_ms
        )
        await list_page.open()
        self._list = list_page

    async def sample(self) -> ListSample:
        """Refresh the page and read a sample; raises ``SessionExpired`` when logged out."""
        list_page = self._list
        if list_page is None:
            raise RuntimeError("WorkflowListSource.sample() before open()")
        await self._session.ensure(list_page.page)
        await list_page.refresh()
        return await list_page.read()

    async def close(self) -> None:
        list_page = self._list
        self._list = None
        if list_page is not None:
            await list_page.close()


class ListWatcher:
    def __init__(
        self,
        workflow: Workflow,
        source: SampleSource,
        reconciler: Reconciler,
        events: EventRepository,
        auth: AuthGate,
        interval_s: float,
    ) -> None:
        self._workflow = workflow
        self._source = source
        self._reconciler = reconciler
        self._events = events
        self._auth = auth
        self._interval_s = interval_s

    async def run_forever(self) -> None:
        """Refresh forever, pausing whenever authentication needs a human.

        Started once per registered workflow via ``BrowserRuntime.spawn``. A failed
        cycle is logged and skipped; only an expired session pauses the whole system.
        """
        await self._source.open()
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
                    self._auth.pause(f"watcher: {exc}")
                except Exception:
                    logger.exception("watcher cycle failed for %s", self._workflow.name)
                    self._events.emit(
                        "sync_failed", workflow=self._workflow.name, detail="see logs"
                    )
                await asyncio.sleep(self._interval_s)
        finally:
            await self._source.close()

    async def refresh_once(self) -> SyncRun:
        """Sample once and reconcile; used by tests and by a manual refresh."""
        return self._reconciler.apply(await self._source.sample())
