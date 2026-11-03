"""Playwright browser session manager for Salesforce UI automation.

Encapsulates everything learned in the POC:
- session-only cookies need snapshotting right after manual login
- auth.json injection makes headless runs login-free until server expiry
- Lightning's lockered LWC dom hides content from plain JS; Playwright's
  text engine (get_by_text) is used for all data extraction
- REST API endpoints reject UI-domain sessions, so extraction happens in-browser
"""
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from . import config, store


def _is_logged_in(url: str) -> bool:
    return "/lightning/" in url and "login" not in url.lower()


class SalesforceSession:
    """Owns a Playwright browser context for one job run."""

    def __init__(self, headless: bool = True,
                 profile_dir: Optional[Path] = None):
        self.headless = headless
        self.profile_dir = profile_dir or config.PROFILE_DIR
        self._pw = None
        self.ctx = None
        self.page = None

    def start(self):
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
        if snapshot:
            state = json.loads(snapshot["storage_state"])
        elif config.AUTH_FILE.exists():
            # legacy pre-DB snapshot file (kept for backward compatibility)
            state = json.loads(config.AUTH_FILE.read_text())
        else:
            state = None
        if state:
            self.ctx.add_cookies(state.get("cookies", []))
        self.page = self.ctx.new_page()
        return self

    def close(self):
        if self.ctx:
            try:
                self.ctx.close()
            except Exception:
                pass
            self.ctx = None
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def __enter__(self):
        # `with` implies a live browser; jobs.py/do_manual_login both call
        # methods (ensure_logged_in / open) without ever calling start().
        if self.page is None or self.ctx is None:
            self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # --- session snapshots -------------------------------------------------
    def save_snapshot(self) -> None:
        """Store the storage_state in SQLite (authoritative session store)."""
        try:
            store.set_auth_snapshot(json.dumps(self.ctx.storage_state()))
        except Exception as e:  # non-fatal: job keeps running
            print(f"! snapshot save failed: {e}", file=sys.stderr)

    # --- navigation --------------------------------------------------------
    def open(self, url: str, wait: float = 0.0):
        self.page.goto(url, wait_until="domcontentloaded", timeout=config.REQUEST_TIMEOUT_MS)
        if wait:
            self.page.wait_for_timeout(int(wait * 1000))
        return self.page

    def wait_logged_in(self, timeout_seconds: float) -> bool:
        """For headful login runs: wait until the user completes Salesforce login."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            self.page.wait_for_timeout(2000)
            if _is_logged_in(self.page.url):
                self.save_snapshot()
                return True
        return False

    def ensure_logged_in(self) -> bool:
        """Headless run: inject cookies; report False if the server session died."""
        page = self.open(f"{config.ORG_BASE}/lightning/", wait=6)
        if _is_logged_in(page.url):
            return True
        # one retry: Lightning sometimes bounces through auth on cold start
        page.goto(f"{config.ORG_BASE}/lightning/", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        return _is_logged_in(page.url)


class SessionExpired(Exception):
    pass


def do_manual_login(reset: bool = False) -> bool:
    """CLI helper: open a headful browser; user logs in; snapshot is saved."""
    if reset and config.PROFILE_DIR.exists():
        shutil.rmtree(config.PROFILE_DIR, ignore_errors=True)
        if config.AUTH_FILE.exists():
            config.AUTH_FILE.unlink()
    with SalesforceSession(headless=False) as s:  # type: ignore[arg-type]
        s.open(f"{config.ORG_BASE}/lightning/", wait=3)
        if _is_logged_in(s.page.url):
            s.save_snapshot()
            print("-> already logged in; session snapshot refreshed")
            return True
        print(f"-> log in manually in the browser window (waiting up to "
              f"{config.LOGIN_WAIT_SECONDS}s)...")
        if s.wait_logged_in(config.LOGIN_WAIT_SECONDS):
            print("-> logged in; session snapshot saved to sqlite (data/app.db)")
            return True
        print("!! timed out waiting for manual login")
        return False


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    ok = do_manual_login(reset=reset)
    sys.exit(0 if ok else 2)
