"""Per-job tab ownership: the parallel-tabs primitive (FR-3.6).

All pages belong to the one warm browser context; a ``TabGroup`` guarantees they are
closed when the job ends, even on failure. Pipelines and adapters depend on the narrow
``TabProvider`` protocol so they can be tested without a browser.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Protocol

from playwright.async_api import BrowserContext, Page

from app.core.job_logger import JobLogger


class TabProvider(Protocol):
    """What a pipeline needs from a tab group."""

    async def new_page(self, url: str) -> Page:
        """Open a tab at ``url`` and return it."""
        ...

    async def close_page(self, page: Page) -> None:
        """Close one tab, ignoring failures."""
        ...


class TabSessions(TabProvider, Protocol):
    """What a job runner needs: tabs it can also tear down as a group."""

    async def close_all(self) -> None:
        """Close every tab this group still owns."""
        ...


class TabGroup:
    """
    Tabs for one job; guarantees cleanup even on failure.

    Every page opened through the group is tracked and closed when the job ends,
    including on exceptions. That is what keeps memory bounded with several jobs in
    flight (NFR-2).

    Example:
        tabs = runtime.new_tab_group(log)
        try:
            page = await tabs.new_page(url)
            ...
        finally:
            await tabs.close_all()
    """

    def __init__(self, context: BrowserContext, timeout_ms: int, log: JobLogger) -> None:
        """Track tabs for one browser context; ``log`` receives tab life-cycle lines."""
        self._context = context
        self._timeout_ms = timeout_ms
        self._log = log
        self._pages: list[Page] = []

    @property
    def open_count(self) -> int:
        """How many tabs this group currently owns."""
        return len(self._pages)

    async def new_page(self, url: str) -> Page:
        """Open and navigate a tab; closes it again if navigation fails."""
        page = await self._context.new_page()
        self._pages.append(page)
        self._watch(page, url)
        try:
            await page.goto(
                url, wait_until="domcontentloaded", timeout=self._timeout_ms
            )
        except BaseException:
            await self.close_page(page)
            raise
        return page

    def _watch(self, page: Page, url: str) -> None:
        """
        Report a tab that dies while the group still owns it.

        Chromium can kill a renderer (memory pressure) and a tab can be closed from
        outside the app; both surface later as ``TargetClosedError`` from an unrelated
        action. Logging the close/crash when it happens, with the URL, is what makes
        such a failure diagnosable in the job log. A close the group initiates is
        silent, because :meth:`close_page` stops tracking the page before closing it.
        """

        def _closed(_page: Page) -> None:
            """Warn only when the group did not close the tab itself."""
            if page in self._pages:
                self._log(f"tab closed while in use: {url}")

        def _crashed(_page: Page) -> None:
            """A renderer crash is always worth a line."""
            self._log(f"tab crashed: {url}")

        page.on("close", _closed)
        page.on("crash", _crashed)

    async def close_page(self, page: Page) -> None:
        """Close one tab and stop tracking it."""
        if page in self._pages:
            self._pages.remove(page)
        with suppress(Exception):
            await page.close()

    @asynccontextmanager
    async def open(self, url: str) -> AsyncIterator[Page]:
        """
        Context manager: open, yield, always close.

        Example:
            async with tabs.open(url) as page:
                await page.get_by_text("Printable View").click()
        """
        page = await self.new_page(url)
        try:
            yield page
        finally:
            await self.close_page(page)

    async def close_all(self) -> None:
        """Close every tracked tab."""
        for page in list(self._pages):
            await self.close_page(page)
