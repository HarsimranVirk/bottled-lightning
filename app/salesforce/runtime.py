"""Owns the single browser and the only asyncio loop that may touch Playwright.

Everything Playwright-related runs on this loop, in its own thread. HTTP handlers and
other threads reach it through ``run()`` (blocking) or ``spawn()`` (fire-and-forget).
"""

from __future__ import annotations

import asyncio
import threading
import traceback
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from contextlib import suppress

from playwright.async_api import BrowserContext, Playwright, async_playwright

from app.config import Settings

from .session import SessionProvider, profile_dir_for
from .tabs import TabGroup


class BrowserRuntime:
    def __init__(self, settings: Settings, session: SessionProvider) -> None:
        self._settings = settings
        self._session = session
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._background: set[Future[object]] = set()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run_loop, name="sf-browser", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=180):
            raise RuntimeError("browser runtime did not start within 180s")
        if self._error is not None:
            self._thread = None
            raise RuntimeError(f"browser runtime failed to start: {self._error}")

    def stop(self) -> None:
        loop, thread = self._loop, self._thread
        if loop is None or thread is None:
            return
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=60)
        self._loop = None
        self._thread = None
        self._context = None

    @property
    def started(self) -> bool:
        return self._loop is not None and self._thread is not None

    @property
    def context(self) -> BrowserContext:
        context = self._context
        if context is None:
            raise RuntimeError("browser runtime not started")
        return context

    def new_tab_group(self) -> TabGroup:
        return TabGroup(self.context, self._settings.request_timeout_ms)

    # -- bridges -----------------------------------------------------------
    def run[T](self, factory: Callable[[], Coroutine[None, None, T]]) -> T:
        """Run a coroutine on the browser loop and wait for its result."""
        loop = self._require_loop()
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            raise RuntimeError("run() cannot be called from the browser loop itself")
        future = asyncio.run_coroutine_threadsafe(factory(), loop)
        return future.result()

    def spawn(self, factory: Callable[[], Coroutine[None, None, object]]) -> None:
        """Start a long-lived task (watcher, dispatcher) on the browser loop."""
        loop = self._require_loop()
        future = asyncio.run_coroutine_threadsafe(factory(), loop)
        self._background.add(future)
        future.add_done_callback(self._background.discard)
        future.add_done_callback(_report_failure)

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None or self._thread is None:
            raise RuntimeError("browser runtime not started — call start() first")
        return loop

    # -- loop thread -------------------------------------------------------
    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._bootstrap())
        except BaseException as exc:  # noqa: BLE001 - reported to start()
            self._error = exc
            self._ready.set()
            with suppress(Exception):
                loop.close()
            self._loop = None
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            with suppress(Exception):
                loop.run_until_complete(self._shutdown())
            with suppress(Exception):
                loop.close()

    async def _bootstrap(self) -> None:
        self._playwright = await async_playwright().start()
        args = ["--disable-blink-features=AutomationControlled"]
        if not self._settings.headless:
            args += ["--start-maximized", "--window-size=1920,1080"]
        context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir_for(self._settings, "worker")),
            headless=self._settings.headless,
            no_viewport=not self._settings.headless,
            args=args,
        )
        await self._session.inject(context)
        self._context = context

    async def _shutdown(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = None
        self._playwright = None
        if context is not None:
            with suppress(Exception):
                await context.close()
        if playwright is not None:
            with suppress(Exception):
                await playwright.stop()


def _report_failure(future: Future[object]) -> None:
    with suppress(Exception):
        error = future.exception()
        if error is not None:
            traceback.print_exception(type(error), error, error.__traceback__)
