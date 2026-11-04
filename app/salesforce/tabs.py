"""Per-job tab ownership: the parallel-tabs primitive (FR-3.6).

All pages belong to the one warm browser context; a ``TabGroup`` guarantees they are
closed when the job ends, even on failure.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from playwright.async_api import BrowserContext, Page


class TabGroup:
    def __init__(self, context: BrowserContext, timeout_ms: int) -> None:
        self._context = context
        self._timeout_ms = timeout_ms
        self._pages: list[Page] = []

    @property
    def open_count(self) -> int:
        return len(self._pages)

    @asynccontextmanager
    async def open(self, url: str) -> AsyncIterator[Page]:
        page = await self._context.new_page()
        self._pages.append(page)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            yield page
        finally:
            if page in self._pages:
                self._pages.remove(page)
            with suppress(Exception):
                await page.close()

    async def close_all(self) -> None:
        for page in list(self._pages):
            with suppress(Exception):
                await page.close()
        self._pages.clear()
