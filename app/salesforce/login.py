"""Manual login: headed browser, wait for the operator, persist the snapshot.

    python -m app.salesforce.login            # login, save snapshot
    python -m app.salesforce.login --reset    # discard saved session, then login

The app's headless runtime keeps its own profile, so this flow never fights it for the
profile lock: the snapshot is saved to SQLite and injected into the running context
(``SessionProvider.reload``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys

from playwright.async_api import Page, async_playwright

from app.config import Settings, load_settings
from app.core.repo.sessions import SessionRepository
from app.db.connection import Database
from app.salesforce.session import is_lightning_url, profile_dir_for


async def _wait_logged_in(page: Page, timeout_s: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(2)
        if is_lightning_url(page.url):
            return True
    return False


async def run_login(
    settings: Settings, repo: SessionRepository, *, reset: bool
) -> bool:
    profile = profile_dir_for(settings, "login")
    if reset:
        repo.clear()
        shutil.rmtree(profile, ignore_errors=True)

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            no_viewport=True,
            args=["--start-maximized", "--window-size=1920,1080"],
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(
                    f"{settings.org_base}/lightning/",
                    wait_until="domcontentloaded",
                    timeout=settings.request_timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001 - operator can still log in manually
                print(f"! navigation failed: {exc}", file=sys.stderr)

            if is_lightning_url(page.url):
                print("-> already logged in; refreshing snapshot", flush=True)
            else:
                print(
                    f"-> log in manually in the browser window "
                    f"(waiting up to {settings.login_wait_s}s)...",
                    flush=True,
                )
                if not await _wait_logged_in(page, float(settings.login_wait_s)):
                    print("!! timed out waiting for manual login", flush=True)
                    return False

            state = await context.storage_state()
            cookies = state.get("cookies", [])
            count = len(cookies) if isinstance(cookies, list) else 0
            repo.save(json.dumps(state), count, settings.org_base)
            repo.event("login", f"{count} cookies")
            print(f"-> login saved ({count} cookies)", flush=True)
            return True
        finally:
            await context.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.salesforce.login")
    parser.add_argument(
        "--reset", action="store_true", help="discard the saved session first"
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    database = Database(settings.db_path)
    database.migrate()
    repo = SessionRepository(database)
    try:
        ok = asyncio.run(run_login(settings, repo, reset=bool(args.reset)))
    finally:
        database.close()
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
