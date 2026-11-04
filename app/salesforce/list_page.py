"""Read one workflow's Salesforce list view into a validated ``ListSample``.

Ported from the pre-refactor extractor, preserving the two behaviours that make it work
against this org: rows come from the Printable View popup (all rows rendered at once),
and record links come from the live list page (virtualised, needs Show more / scrolling).
"""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress

from playwright.async_api import BrowserContext, Page

from app.core.list_view import ListRow, ListSample, ListViewSpec
from app.core.models import utcnow

_ITEM_TOTAL = re.compile(r"(\d[\d,]*)\s+items?\b")
_SHOW_MORE = re.compile(r"^\s*Show more\s*$", re.IGNORECASE)
_APPROVAL_DATE_COLUMN = 6
_ROW_KEY_COLUMN = 1


def parse_item_total(text: str) -> int | None:
    """``"12 items • Updated a moment ago"`` → ``12``. Pure, so it is unit-tested."""
    match = _ITEM_TOTAL.search(text)
    if match is None:
        return None
    return int(match.group(1).replace(",", ""))


class ListPage:
    """Owns one always-open list-view page (FR-2.1)."""

    def __init__(
        self,
        context: BrowserContext,
        page: Page,
        spec: ListViewSpec,
        timeout_ms: int,
    ) -> None:
        self._context = context
        self._page = page
        self._spec = spec
        self._timeout_ms = timeout_ms
        self._pattern = re.compile(spec.pattern)

    @property
    def page(self) -> Page:
        return self._page

    async def open(self) -> None:
        await self._page.goto(
            self._spec.url, wait_until="domcontentloaded", timeout=self._timeout_ms
        )
        await self._page.wait_for_timeout(3000)
        await self._wait_for_rows()

    async def refresh(self) -> None:
        await self._page.reload(
            wait_until="domcontentloaded", timeout=self._timeout_ms
        )
        await self._wait_for_rows()

    async def read(self) -> ListSample:
        """Sample the page. Validity is decided by ``ListSample.valid`` (FR-2.9)."""
        header_total = await self._read_total()
        links = await self._collect_links(target=header_total)
        printable = await self._printable_rows()
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
        with suppress(Exception):
            await self._page.close()

    # -- header ------------------------------------------------------------
    async def _read_total(self) -> int | None:
        locator = self._page.get_by_text(
            re.compile(r"\d[\d,]*\s+items?\b")
        ).first
        try:
            text = await locator.inner_text(timeout=5000)
        except Exception:  # noqa: BLE001 - header absent means "invalid sample"
            return None
        return parse_item_total(text)

    # -- rows --------------------------------------------------------------
    async def _wait_for_rows(self, timeout_s: float = 60.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1.5)
            try:
                if await self._page.get_by_text(self._pattern).count() > 0:
                    return
            except Exception:  # noqa: BLE001, S112 - page may be mid-navigation
                continue

    async def _printable_rows(self) -> dict[str, ListRow]:
        button = self._page.get_by_role("button", name="Printable View")
        if await button.count() == 0:
            return {}
        try:
            async with self._context.expect_page(
                timeout=25_000
            ) as popup_info:
                await button.first.click(timeout=self._timeout_ms)
            popup = await popup_info.value
        except Exception:  # noqa: BLE001 - fall back to scrolling only
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
        links = self._page.get_by_role("link")
        count = await links.count()
        for index in range(count):
            locator = links.nth(index)
            try:
                text = await locator.inner_text(timeout=1000) or ""
            except Exception:  # noqa: BLE001, S112 - virtualised rows detach
                continue
            match = self._pattern.search(text)
            if match is None:
                continue
            href = await locator.get_attribute("href")
            if href and "/lightning/r/" in href:
                found.setdefault(match.group(0).strip(), href)

    async def _show_more(self) -> bool:
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
    rows: dict[str, ListRow] = {}
    tables = page.locator("table")
    if await tables.count() == 0:
        return rows
    trs = tables.first.locator("tr")
    count = await trs.count()
    for index in range(1, count):
        cells = trs.nth(index).locator("td")
        try:
            if await cells.count() <= _APPROVAL_DATE_COLUMN:
                continue
            key_text = (await cells.nth(_ROW_KEY_COLUMN).inner_text(timeout=500)).strip()
        except Exception:  # noqa: BLE001, S112 - row may not be a data row
            continue
        match = pattern.search(key_text)
        if match is None:
            continue
        key = match.group(0).strip()
        try:
            approved = (
                await cells.nth(_APPROVAL_DATE_COLUMN).inner_text(timeout=500)
            ).strip()
        except Exception:  # noqa: BLE001
            approved = ""
        rows.setdefault(
            key,
            ListRow(key=key, href="", columns={}, approved_at=approved or None),
        )
    return rows
