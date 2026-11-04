"""Async Playwright DOM helpers used by the Salesforce layer and adapters.

Nothing here knows about a specific SF object; the workflow-specific parts (selectors,
URL fields, field labels) stay in the adapter modules.
"""

from __future__ import annotations

import logging
from contextlib import suppress

from playwright.async_api import Locator, Page

logger = logging.getLogger(__name__)


async def safe_inner_text(locator: Locator, timeout_ms: int = 2000) -> str | None:
    """Element text, or ``None`` when the element detached."""
    try:
        text = await locator.inner_text(timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - detached or still rendering
        logger.debug("inner_text failed: %s", exc)
        return None
    return text.strip() or None


async def safe_body_text(page: Page, timeout_ms: int = 10_000) -> str | None:
    """Page body text, or ``None``."""
    return await safe_inner_text(page.locator("body"), timeout_ms)


async def dismiss_banner(page: Page) -> None:
    """Salesforce shows a "Dismiss" toast that can cover the record body."""
    dismiss = page.get_by_text("Dismiss", exact=True).first
    with suppress(Exception):
        if await dismiss.count() > 0 and await dismiss.is_visible():
            await dismiss.click(timeout=2000)


def absolute_url(href: str, org_base: str) -> str:
    """Join an href against the org base when it is relative."""
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
