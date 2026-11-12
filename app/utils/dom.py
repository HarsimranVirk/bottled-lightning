"""Async Playwright DOM helpers used by the Salesforce layer and adapters.

Nothing here knows about a specific SF object; the workflow-specific parts (selectors,
URL fields, field labels) stay in the adapter modules.

Every retrying helper is bounded by **real elapsed time**. A Playwright ``timeout=``
only bounds one action; a loop that counts a nominal interval while each attempt blocks
for its own timeout can run for hours. ``Deadline`` measures a monotonic budget and the
helpers pass the *remaining* budget to the next action (FR-7.12).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import partial
from typing import Protocol

from playwright.async_api import Locator, Page

logger = logging.getLogger(__name__)

#: Default retry interval for the polling helpers, in milliseconds.
_POLL_INTERVAL_MS = 500

#: Default read budget for a single element text, in milliseconds.
_TEXT_TIMEOUT_MS = 2000


class Deadline:
    """
    Monotonic wall-clock budget for one bounded wait.

    Playwright's per-action ``timeout`` only bounds one action; a retry loop that adds
    a nominal interval can run far past it when an attempt itself blocks. Helpers use
    this class to measure real elapsed time and hand the *remaining* budget to the next
    action.

    Example:
        deadline = Deadline(60_000)
        while not deadline.expired:
            await locator.click(timeout=deadline.action_ms())
    """

    def __init__(self, timeout_ms: int) -> None:
        """Start the budget now; zero or negative means already expired."""
        self._expires_at = time.monotonic() + max(0, timeout_ms) / 1000

    @property
    def expired(self) -> bool:
        """Whether the budget is used up."""
        return time.monotonic() >= self._expires_at

    def remaining_ms(self) -> int:
        """Milliseconds left, floored at zero."""
        return max(0, int((self._expires_at - time.monotonic()) * 1000))

    def action_ms(self) -> float:
        """Timeout for the next Playwright action: the remaining budget, at least 1 ms."""
        return max(1.0, self._expires_at * 1000 - time.monotonic() * 1000)

    def sleep_s(self, cap_s: float) -> float:
        """A retry sleep capped by the remaining budget, in seconds."""
        return min(cap_s, self.remaining_ms() / 1000)


class LocatorLike(Protocol):
    """
    The subset of Playwright's ``Locator`` the wait helpers use.

    Real ``Locator`` objects satisfy this structurally. Unit tests can pass a fake
    locator without a browser and without escaping types.
    """

    async def count(self) -> int:
        """Number of matching elements."""
        ...

    def nth(self, index: int) -> LocatorLike:
        """The locator for the element at ``index``."""
        ...

    async def is_visible(self) -> bool:
        """Whether the element is visible."""
        ...

    async def click(self, *, timeout: float | None = None) -> None:
        """Click the element, waiting up to ``timeout`` milliseconds."""
        ...

    async def fill(self, value: str, *, timeout: float | None = None) -> None:
        """Fill the input with ``value``, waiting up to ``timeout`` milliseconds."""
        ...

    async def input_value(self, *, timeout: float | None = None) -> str:
        """The input's current value, waiting up to ``timeout`` milliseconds."""
        ...


async def bounded[T](factory: Callable[[], Awaitable[T]], deadline: Deadline) -> T:
    """
    Run one awaitable within the deadline's remaining budget.

    The *factory* form is deliberate: when the budget is already spent the coroutine is
    never created, so no work starts after the deadline and no coroutine is left
    unawaited. Expiry raises the builtin ``TimeoutError``; external task cancellation
    still propagates as ``CancelledError``.

    Raises:
        TimeoutError: the budget expired before (or while) the awaitable completed.
    """
    if deadline.expired:
        raise TimeoutError("deadline expired")
    async with asyncio.timeout(deadline.action_ms() / 1000):
        return await factory()


async def poll(
    check: Callable[[], Awaitable[bool]], timeout_ms: int, interval_ms: int = 500
) -> bool:
    """
    Wait until an async predicate is true, or the real-time budget expires.

    Used for Lightning/LWC updates that do not fire a navigation event: lazy field
    sections, inline-edit inputs appearing, and values re-rendering after Save. Each
    predicate run is bounded by the remaining budget, so a slow check (for example a
    label scan) cannot multiply the timeout. An exception (a detached locator during a
    re-render) counts as "not yet" and is logged at debug level.

    Example:
        ready = await poll(
            lambda: _count(field.locator(".test-id__field-value")) > 0,
            timeout_ms,
        )
    """
    deadline = Deadline(timeout_ms)
    while not deadline.expired:
        try:
            if await bounded(check, deadline):
                return True
        except TimeoutError:
            return False
        except Exception as exc:  # noqa: BLE001 - detached during a re-render
            logger.debug("poll check failed: %s", exc)
        if deadline.expired:
            return False
        await asyncio.sleep(deadline.sleep_s(interval_ms / 1000))
    return False


async def click_first_visible(locator: LocatorLike, timeout_ms: int) -> bool:
    """
    Click the first visible match, retrying while the list re-renders.

    Classic pages render duplicate Save/Cancel controls at the top and bottom of the
    page; only one is in the viewport. Each ``count``/``is_visible``/``click`` is bounded
    by the **remaining** budget, and no retry starts after it is spent, so a visible but
    unclickable control cannot extend a 60-second wait into hours.

    Returns ``False`` when no match becomes clickable before the deadline.
    """
    deadline = Deadline(timeout_ms)
    while not deadline.expired:
        try:
            count = await bounded(locator.count, deadline)
        except TimeoutError:
            return False
        except Exception as exc:  # noqa: BLE001 - locator may be re-rendering
            logger.debug("locator count failed: %s", exc)
            count = 0
        for index in range(count):
            if deadline.expired:
                return False
            candidate = locator.nth(index)
            try:
                if not await bounded(candidate.is_visible, deadline):
                    continue
                await bounded(
                    partial(candidate.click, timeout=deadline.action_ms()), deadline
                )
                return True
            except TimeoutError:
                return False
            except Exception as exc:  # noqa: BLE001 - stale handle or overlay
                logger.debug("click candidate %s failed: %s", index, exc)
        if deadline.expired:
            return False
        await asyncio.sleep(deadline.sleep_s(_POLL_INTERVAL_MS / 1000))
    return False


async def clear_and_fill(locator: LocatorLike, value: str, timeout_ms: int) -> str:
    """
    Clear an input before filling it, then return the value the widget reports.

    Lightning/LWC inputs can retain their formatted text when ``fill()`` is called on a
    non-empty field, which can concatenate the old and new amounts. Clearing first makes
    every write deterministic. The caller must verify the returned value against the
    intended value before clicking Save; a mismatch must abort the write.

    Every action receives the remaining budget of ``timeout_ms``. A budget that expires
    raises ``TimeoutError`` so the adapter can return ``WriteOutcome.UNKNOWN``.
    """
    deadline = Deadline(timeout_ms)
    await bounded(lambda: locator.fill("", timeout=deadline.action_ms()), deadline)
    await bounded(lambda: locator.fill(value, timeout=deadline.action_ms()), deadline)
    return await bounded(
        lambda: locator.input_value(timeout=deadline.action_ms()), deadline
    )


async def safe_inner_text(locator: Locator, timeout_ms: int = _TEXT_TIMEOUT_MS) -> str | None:
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


#: Salesforce text shown by a related list that rendered with no rows. Both the
#: Lightning list ("No items to display") and the Classic one ("No records to
#: display") are matched, because some refs land on either.
_EMPTY_LIST_PATTERN = r"No (items|records) to display"


def related_list_empty(page: Page) -> Locator:
    """
    Locator for a related list's "no items" text.

    Used together with :func:`settled_row_count` so an empty related list is proven by
    Salesforce's own message instead of by a row count that never rendered.
    """
    return page.get_by_text(re.compile(_EMPTY_LIST_PATTERN, re.IGNORECASE))


async def settled_row_count(
    rows: LocatorLike, empty_marker: LocatorLike, timeout_ms: int
) -> int | None:
    """
    Wait for a related list to settle into rows or into a positive empty state.

    Returns ``>= 1`` when rows rendered, ``0`` only when Salesforce showed its "no
    items" text, and ``None`` when neither appeared before the budget expired. ``None``
    is deliberately distinct from ``0``: a list that never rendered tells us nothing,
    and callers must report it as ``UNRESOLVED`` rather than "no matching records".

    Example:
        count = await settled_row_count(
            page.locator("tr.slds-hint-parent"), related_list_empty(page), 20_000
        )
        if count is None: …couldn't open the list…
        elif count == 0: …genuinely empty…
    """
    deadline = Deadline(timeout_ms)
    while not deadline.expired:
        try:
            count = await bounded(rows.count, deadline)
        except TimeoutError:
            return None
        except Exception as exc:  # noqa: BLE001 - the list may still be re-rendering
            logger.debug("related-list row count failed: %s", exc)
            count = 0
        if count > 0:
            return count
        try:
            if await bounded(empty_marker.count, deadline) > 0:
                return 0
        except TimeoutError:
            return None
        except Exception as exc:  # noqa: BLE001 - marker not rendered yet
            logger.debug("related-list empty check failed: %s", exc)
        if deadline.expired:
            return None
        await asyncio.sleep(deadline.sleep_s(_POLL_INTERVAL_MS / 1000))
    return None


async def wait_for_text(page: Page, text: str, timeout_ms: int) -> bool:
    """
    Wait until the page body contains ``text`` (case-insensitive).

    The body read is capped by the remaining budget, so a slow render cannot multiply
    the configured timeout by the read timeout.
    """
    deadline = Deadline(timeout_ms)
    lowered = text.lower()
    while not deadline.expired:
        try:
            body = await bounded(
                lambda: safe_body_text(
                    page, max(1, min(3000, deadline.remaining_ms()))
                ),
                deadline,
            )
        except TimeoutError:
            return False
        if body is not None and lowered in body.lower():
            return True
        if deadline.expired:
            return False
        await page.wait_for_timeout(max(0, min(_POLL_INTERVAL_MS, deadline.remaining_ms())))
    return False
