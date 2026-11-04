"""Small async DOM helpers shared by the Z02 adapters."""

from __future__ import annotations

import logging
import re
from contextlib import suppress

from playwright.async_api import Locator, Page

logger = logging.getLogger(__name__)


async def safe_inner_text(locator: Locator, timeout_ms: int = 2000) -> str | None:
    try:
        text = await locator.inner_text(timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - detached or still rendering
        logger.debug("inner_text failed: %s", exc)
        return None
    return text.strip() or None


async def safe_body_text(page: Page, timeout_ms: int = 10_000) -> str | None:
    return await safe_inner_text(page.locator("body"), timeout_ms)


async def dismiss_banner(page: Page) -> None:
    """Salesforce shows a "Dismiss" toast that can cover the record body."""
    dismiss = page.get_by_text("Dismiss", exact=True).first
    with suppress(Exception):
        if await dismiss.count() > 0 and await dismiss.is_visible():
            await dismiss.click(timeout=2000)


async def click_show_more(page: Page, max_clicks: int = 300) -> int:
    pattern = re.compile(r"^\s*Show more\s*$", re.IGNORECASE)
    clicked = 0
    while clicked < max_clicks:
        locator = page.get_by_role("button", name=pattern)
        if await locator.count() == 0:
            break
        try:
            await locator.first.click(timeout=5000)
        except Exception as exc:  # noqa: BLE001 - best effort
            logger.debug("show more click failed: %s", exc)
            break
        clicked += 1
        await page.wait_for_timeout(2000)
    return clicked


async def wait_for_count(
    locator: Locator, minimum: int, timeout_s: float, page: Page
) -> bool:
    """Poll a locator count until it reaches ``minimum`` or the deadline passes."""
    deadline = timeout_s * 1000
    waited = 0.0
    while waited < deadline:
        if await locator.count() >= minimum:
            return True
        await page.wait_for_timeout(300)
        waited += 300
    return await locator.count() >= minimum


def absolute_url(href: str, org_base: str) -> str:
    if href.startswith("http"):
        return href
    return f"{org_base}{href}"


def related_list_url(record_url: str, related_name: str) -> str:
    """``…/r/Opportunity/ID/view`` → ``…/r/Opportunity/ID/related/<rel>/view``."""
    return record_url.replace("/view", f"/related/{related_name}/view")


async def wait_for_rows(
    locator: Locator, page: Page, timeout_ms: int, minimum: int = 1
) -> int:
    """Wait until a related list renders at least ``minimum`` rows."""
    waited = 0
    while waited < timeout_ms:
        count = await locator.count()
        if count >= minimum:
            return count
        await page.wait_for_timeout(500)
        waited += 500
    return await locator.count()


async def wait_for_text(page: Page, text: str, timeout_ms: int) -> bool:
    """Wait until the page body contains ``text`` (case-insensitive)."""
    waited = 0
    while waited < timeout_ms:
        body = await safe_body_text(page, 3000) or ""
        if text.lower() in body.lower():
            return True
        await page.wait_for_timeout(500)
        waited += 500
    return False
