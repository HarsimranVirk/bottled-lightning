"""Read one workflow's Salesforce list view into a validated ``ListSample``.

Ported from the pre-refactor extractor, preserving the two behaviours that make it work
against this org: rows come from the Printable View popup (all rows rendered at once),
and record links come from the live list page (virtualised, needs Show more / scrolling).
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, Page

from app.core.list_view import ListRow, ListSample, ListViewSpec
from app.core.models import utcnow

logger = logging.getLogger(__name__)

_ITEM_TOTAL = re.compile(r"(\d[\d,]*)\s+items?\b")
_HEADER_TEXT = re.compile(r"\d[\d,]*\s+items?\b")
_SHOW_MORE = re.compile(r"^\s*Show more\s*$", re.IGNORECASE)
_APPROVAL_DATE_COLUMN = 6
_ROW_KEY_COLUMN = 1


def resolve_href(current_url: str, href: str) -> str:
    """Absolute URL for a list link; Lightning renders root-relative hrefs.

    The stored ``record_url`` is opened directly by the UI, so a bare
    ``/lightning/r/…`` would resolve against the local app host instead of Salesforce.
    """
    return urljoin(current_url, href)


def parse_item_total(text: str) -> int | None:
    """``"12 items • Updated a moment ago"`` → ``12``. Pure, so it is unit-tested."""
    match = _ITEM_TOTAL.search(text)
    if match is None:
        return None
    return int(match.group(1).replace(",", ""))


class ListPage:
    """
    Owns one always-open list-view page (FR-2.1).

    A sample combines three reads: the header total, the record links from the
    live (virtualised) list, and all rows plus approval dates from the Printable
    View popup. Validity is decided afterwards by ``ListSample.valid``.

    Example:
        page = await context.new_page()
        lp = ListPage(context, page, spec, timeout_ms)
        await lp.open()
        sample = await lp.read()
    """

    def __init__(
        self,
        context: BrowserContext,
        page: Page,
        spec: ListViewSpec,
        timeout_ms: int,
    ) -> None:
        """Wrap one always-open page for one list view."""
        self._context = context
        self._page = page
        self._spec = spec
        self._timeout_ms = timeout_ms
        self._pattern = re.compile(spec.pattern)

    @property
    def page(self) -> Page:
        """The underlying Playwright page."""
        return self._page

    async def open(self) -> None:
        """Navigate to the list view and wait for rows *and* the header total.

        Waiting for the header matters: Lightning paints the rows before the "N items"
        header, so a read that only waited for rows recorded an invalid first sample at
        every process start.
        """
        await self._page.goto(
            self._spec.url, wait_until="domcontentloaded", timeout=self._timeout_ms
        )
        await self._page.wait_for_timeout(3000)
        await self._wait_for_rows()
        await self._wait_for_header()

    async def refresh(self) -> None:
        """Reload the list view and wait for rows *and* the header total."""
        await self._page.reload(
            wait_until="domcontentloaded", timeout=self._timeout_ms
        )
        await self._wait_for_rows()
        await self._wait_for_header()

    async def read(self) -> ListSample:
        """
        Sample the page; validity is decided by ``ListSample.valid``.

        Printable view is read first because it needs a freshly rendered page; the
        link pass comes second because it scrolls. If the popup is unavailable the
        sample still has rows (from links) but no approval dates — and its validity
        depends only on the header/row count.
        """
        header_total = await self._read_total()
        # Printable view first: it needs a clean, freshly rendered list page. The record
        # links are collected afterwards because that pass scrolls the page.
        printable = await self._printable_rows()
        links = await self._collect_links(target=header_total)
        keys = set(printable) | set(links)
        rows = tuple(
            ListRow(
                key=key,
                href=links.get(key, ""),
                columns={},
                approved_at=(
                    printable[key].approved_at if key in printable else None
                ),
            )
            for key in sorted(keys)
        )
        return ListSample(
            captured_at=utcnow(), header_total=header_total, rows=rows
        )

    async def close(self) -> None:
        """Close the page."""
        with suppress(Exception):
            await self._page.close()

    # -- header ------------------------------------------------------------
    async def _wait_for_header(self, timeout_s: float = 20.0) -> None:
        """Wait until the "N items" header renders; bounded, never raises."""
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            try:
                if await self._page.get_by_text(_HEADER_TEXT).count() > 0:
                    return
            except Exception as exc:  # noqa: BLE001 - page may be navigating
                logger.debug("header wait failed: %s", exc)
            await asyncio.sleep(0.5)

    async def _read_total(self) -> int | None:
        """Read the header total; ``None`` when it never renders."""
        locator = self._page.get_by_text(_HEADER_TEXT).first
        try:
            text = await locator.inner_text(timeout=5000)
        except Exception:  # noqa: BLE001 - header absent means "invalid sample"
            return None
        return parse_item_total(text)

    # -- rows --------------------------------------------------------------
    async def _wait_for_rows(self, timeout_s: float = 60.0) -> None:
        """Wait until at least one row matches the key pattern."""
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1.5)
            try:
                if await self._page.get_by_text(self._pattern).count() > 0:
                    return
            except Exception as exc:  # noqa: BLE001 - page may be mid-navigation
                logger.debug("list view not ready yet: %s", exc)

    async def _printable_rows(self) -> dict[str, ListRow]:
        """Read all rows from the Printable View popup."""
        button = self._page.get_by_role("button", name="Printable View")
        waited = 0
        while waited < self._timeout_ms:
            if await button.count() > 0:
                break
            await self._page.wait_for_timeout(500)
            waited += 500
        if await button.count() == 0:
            logger.debug("printable view button not found")
            return {}
        try:
            async with self._context.expect_page(timeout=25_000) as popup_info:
                await button.first.click(timeout=self._timeout_ms)
            popup = await popup_info.value
        except Exception as exc:  # noqa: BLE001 - fall back to scrolling only
            logger.debug("printable view unavailable: %s", exc)
            return {}

        rows: dict[str, ListRow] = {}
        try:
            await popup.wait_for_load_state(
                "domcontentloaded", timeout=self._timeout_ms
            )
            stable = 0
            for _ in range(40):
                await popup.wait_for_timeout(1000)
                batch = await _parse_table(popup, self._pattern)
                new = set(batch) - set(rows)
                for key, row in batch.items():
                    rows.setdefault(key, row)
                stable = stable + 1 if (batch and not new) else 0
                if stable >= 3 and rows:
                    break
        finally:
            with suppress(Exception):
                await popup.close()
        return rows

    # -- links -------------------------------------------------------------
    async def _collect_links(self, target: int | None) -> dict[str, str]:
        """Collect record hrefs from the virtualised list page."""
        found: dict[str, str] = {}
        idle = 0
        while idle < 4:
            await self._scan_links(found)
            if target is not None and len(found) >= target:
                break
            if await self._show_more():
                idle = 0
                continue
            with suppress(Exception):
                await self._page.keyboard.press("End")
                await self._page.mouse.wheel(0, 20000)
            await self._page.wait_for_timeout(2000)
            previous = len(found)
            await self._scan_links(found)
            idle = idle + 1 if len(found) <= previous else 0
        return found

    async def _scan_links(self, found: dict[str, str]) -> None:
        """One scan of the visible links into ``found``."""
        links = self._page.get_by_role("link")
        count = await links.count()
        for index in range(count):
            locator = links.nth(index)
            try:
                text = await locator.inner_text(timeout=1000) or ""
            except Exception as exc:  # noqa: BLE001 - virtualised rows detach
                logger.debug("skipping detached list link %d: %s", index, exc)
                continue
            match = self._pattern.search(text)
            if match is None:
                continue
            href = await locator.get_attribute("href")
            if href and "/lightning/r/" in href:
                found.setdefault(
                    match.group(0).strip(), resolve_href(self._page.url, href)
                )

    async def _show_more(self) -> bool:
        """Click Show more once; returns whether anything was clicked."""
        locator = self._page.get_by_role("button", name=_SHOW_MORE)
        try:
            if await locator.count() == 0:
                return False
            await locator.first.click(timeout=5000)
            await self._page.wait_for_timeout(2000)
            return True
        except Exception:  # noqa: BLE001 - clicking is best effort
            return False


async def _parse_table(page: Page, pattern: re.Pattern[str]) -> dict[str, ListRow]:
    """Parse data rows out of the printable-view table."""
    rows: dict[str, ListRow] = {}
    tables = page.locator("table")
    if await tables.count() == 0:
        return rows
    trs = tables.first.locator("tr")
    count = await trs.count()
    for index in range(1, count):
        # Header/row-header cells can be ``th``; include both so column indexes match
        # the visible table layout.
        cells = trs.nth(index).locator("td, th")
        try:
            if await cells.count() <= _APPROVAL_DATE_COLUMN:
                continue
            key_text = (await cells.nth(_ROW_KEY_COLUMN).inner_text(timeout=500)).strip()
        except Exception as exc:  # noqa: BLE001 - row may not be a data row
            logger.debug("skipping non-data table row %d: %s", index, exc)
            continue
        match = pattern.search(key_text)
        if match is None:
            continue
        key = match.group(0).strip()
        try:
            approved = (
                await cells.nth(_APPROVAL_DATE_COLUMN).inner_text(timeout=500)
            ).strip()
        except Exception as exc:  # noqa: BLE001 - date column is optional
            logger.debug("no approval date for %s: %s", key, exc)
            approved = ""
        rows.setdefault(
            key,
            ListRow(key=key, href="", columns={}, approved_at=approved or None),
        )
    return rows
