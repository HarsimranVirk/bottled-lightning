"""Playwright browser session manager for Salesforce UI automation."""

import json
import shutil
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, cast

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    StorageState,
    sync_playwright,
)

from . import config, store

__all__ = ["SalesforceSession", "SessionExpired"]


class SessionExpired(Exception):
    pass


def _is_logged_in(url: str) -> bool:
    return "/lightning/" in url and "login" not in url.lower()


class SalesforceSession:
    """Owns a Playwright browser context for one job run."""

    headless: bool
    profile_dir: Path
    _pw: Playwright | None
    ctx: BrowserContext | None
    page: Page | None

    def __init__(
        self,
        headless: bool = True,
        profile_dir: Path | None = None,
    ) -> None:
        self.headless = headless
        self.profile_dir = profile_dir or config.PROFILE_DIR
        self._pw = None
        self.ctx = None
        self.page = None

    def require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("session not started — call start() first")
        return self.page

    def require_context(self) -> BrowserContext:
        if self.ctx is None:
            raise RuntimeError("session not started — call start() first")
        return self.ctx

    def start(self) -> Self:
        self._pw = sync_playwright().start()
        args = ["--disable-blink-features=AutomationControlled"]
        if not self.headless:
            args += ["--start-maximized", "--window-size=1920,1080"]
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=self.headless,
            no_viewport=not self.headless,
            args=args,
        )
        snapshot = store.get_auth_snapshot()
        state: StorageState | None = None
        if snapshot:
            raw = json.loads(str(snapshot["storage_state"]))
            if isinstance(raw, dict):
                state = cast(StorageState, raw)
        elif config.AUTH_FILE.exists():
            raw = json.loads(config.AUTH_FILE.read_text())
            if isinstance(raw, dict):
                state = cast(StorageState, raw)
        if state is not None:
            cookies = state.get("cookies", [])
            if isinstance(cookies, list):
                self.ctx.add_cookies(cookies)  # type: ignore[arg-type]  # storage-state cookies are structurally SetCookieParam
        self.page = self.ctx.new_page()
        return self

    def close(self) -> None:
        if self.ctx:
            try:
                self.ctx.close()
            except Exception as e:  # noqa: BLE001
                print(f"! close failed: {e}", file=__import__("sys").stderr)
            self.ctx = None
        if self._pw:
            try:
                self._pw.stop()
            except Exception as e:  # noqa: BLE001
                print(f"! stop failed: {e}", file=__import__("sys").stderr)
            self._pw = None

    def __enter__(self) -> Self:
        if self.page is None or self.ctx is None:
            self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self.close()
        return False

    def save_snapshot(self) -> None:
        try:
            store.set_auth_snapshot(json.dumps(self.require_context().storage_state()))
        except Exception as e:  # noqa: BLE001
            print(f"! snapshot save failed: {e}", file=__import__("sys").stderr)

    def open(self, url: str, wait: float = 0.0) -> Page:
        page = self.require_page()
        page.goto(url, wait_until="domcontentloaded", timeout=config.REQUEST_TIMEOUT_MS)
        if wait:
            page.wait_for_timeout(int(wait * 1000))
        return page

    def open_tab(self, url: str, wait: float = 0.0) -> Page:
        page = self.require_context().new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=config.REQUEST_TIMEOUT_MS)
        if wait:
            page.wait_for_timeout(int(wait * 1000))
        return page

    def ensure_logged_in(self) -> bool:
        page = self.require_page()
        if page.url and _is_logged_in(page.url):
            return True
        target = f"{config.ORG_BASE}/lightning/"
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=config.REQUEST_TIMEOUT_MS)
        except Exception as e:  # noqa: BLE001
            print(f"! nav failed: {e}", file=__import__("sys").stderr)
        if _is_logged_in(page.url):
            return True
        # one retry: Lightning sometimes bounces through auth on cold start
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=config.REQUEST_TIMEOUT_MS)
            page.wait_for_timeout(6000)
        except Exception as e:  # noqa: BLE001
            print(f"! nav failed: {e}", file=__import__("sys").stderr)
        return _is_logged_in(page.url)

    def wait_logged_in(self, timeout_seconds: float) -> bool:
        page = self.require_page()
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            if page.url and _is_logged_in(page.url):
                self.save_snapshot()
                return True
        return False


def do_manual_login(reset: bool = False) -> bool:
    if reset:
        if config.PROFILE_DIR.exists():
            shutil.rmtree(config.PROFILE_DIR, ignore_errors=True)
        store.clear_auth_snapshot()
        legacy = config.AUTH_FILE
        if legacy.exists():
            try:
                legacy.unlink()
            except OSError:
                pass
    with SalesforceSession(headless=False) as session:
        page = session.require_page() if session.page is not None else None
        try:
            session.open(f"{config.ORG_BASE}/lightning/", wait=3)
        except Exception as e:  # noqa: BLE001
            print(f"! nav failed: {e}", file=sys.stderr)
        page = session.require_page()
        if page.url and _is_logged_in(page.url):
            session.save_snapshot()
            print("-> already logged in; session snapshot refreshed", flush=True)
            return True
        print(
            f"-> log in manually in the browser window (waiting up to "
            f"{config.LOGIN_WAIT_SECONDS}s)...",
            flush=True,
        )
        if session.wait_logged_in(config.LOGIN_WAIT_SECONDS):
            print("-> logged in; snapshot saved", flush=True)
            return True
        print("!! timed out waiting for manual login", flush=True)
        return False


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    ok = do_manual_login(reset=reset)
    sys.exit(0 if ok else 2)
