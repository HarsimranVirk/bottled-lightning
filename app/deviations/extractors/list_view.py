"""List-view extraction strategies (printable view primary, scroll fallback)."""

import re

from playwright.sync_api import BrowserContext, Page

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile

from .common import click_show_more, collect_matches, looks_logged_in, read_item_total


def extract_via_printable_view(
    page: Page, ctx: BrowserContext, pattern: str
) -> tuple[set[str], dict[str, str]]:
    numbers: set[str] = set()
    approval_dates: dict[str, str] = {}
    try:
        btn = page.get_by_role("button", name="Printable View")
        if btn.count() == 0:
            return numbers, approval_dates
        with ctx.expect_page(timeout=25_000) as popup_info:
            btn.first.click()
        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded", timeout=40_000)
        stable = 0
        rx = re.compile(pattern)
        for _ in range(40):
            popup.wait_for_timeout(1000)
            batch = collect_matches(popup, pattern)
            if batch and batch == numbers:
                stable += 1
            else:
                stable = 0
            numbers |= batch
            # capture approval date per row (column index 6)
            try:
                tables = popup.locator("table")
                if tables.count() > 0:
                    rows = tables.first.locator("tr")
                    for ri in range(1, rows.count()):
                        cells = rows.nth(ri).locator("td")
                        if cells.count() < 7:
                            continue
                        num_text = cells.nth(1).inner_text(timeout=500).strip()
                        m = rx.search(num_text)
                        if not m:
                            continue
                        key = m.group(0).strip()
                        ad = cells.nth(6).inner_text(timeout=500).strip()
                        if ad and key not in approval_dates:
                            approval_dates[key] = ad
            except Exception:  # noqa: BLE001, S110
                pass
            if stable >= 3 and numbers:
                break
        popup.close()
        return numbers, approval_dates
    except Exception:  # noqa: BLE001
        return numbers, approval_dates


def extract_via_scroll(
    page: Page,
    pattern: str,
    target: int | None = None,
    max_idle_rounds: int = 4,
) -> set[str]:
    numbers: set[str] = set()
    idle = 0
    while idle < max_idle_rounds:
        page.keyboard.press("End")
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(2000)
        if (target is None or len(numbers) < target) and click_show_more(page, max_clicks=1):
            idle = 0
            continue
        new = collect_matches(page, pattern)
        added = len(new - numbers)
        numbers |= new
        if target is not None and len(numbers) >= target:
            break
        idle = idle + 1 if added == 0 else 0
    click_show_more(page)
    final = collect_matches(page, pattern)
    numbers |= final
    return numbers


def extract_list_view(
    profile: WorkflowProfile, session: SalesforceSession
) -> tuple[set[str], int | None, dict[str, str]]:
    page = session.open(profile.list_url, wait=3)
    if not looks_logged_in(page):
        from ...browser import SessionExpired  # local import to avoid cycle

        raise SessionExpired(f"not logged in for {profile.list_url}")
    from .common import wait_for_data

    wait_for_data(page, profile.pattern)
    total = read_item_total(page)
    numbers, approval_dates = extract_via_printable_view(
        page, session.require_context(), profile.pattern
    )
    if not numbers:
        numbers = extract_via_scroll(page, profile.pattern, target=total)
        approval_dates = {}
    return numbers, total, approval_dates


def collect_record_links(page: Page, pattern: str, target: int | None = None) -> dict[str, str]:
    rx = re.compile(pattern)
    found: dict[str, str] = {}
    idle = 0
    while idle < 4:
        links = page.get_by_role("link")
        n = links.count()
        for i in range(n):
            try:
                loc = links.nth(i)
                txt = loc.inner_text(timeout=1000) or ""
                m = rx.search(txt)
                if not m:
                    continue
                href = loc.get_attribute("href")
                if href and "/lightning/r/" in href:
                    _k = m.group(0).strip()
                    if _k not in found:
                        found[_k] = href
            except Exception as e:  # noqa: BLE001
                print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
                continue
        if target is not None and len(found) >= target:
            break
        if click_show_more(page, max_clicks=1):
            idle = 0
            continue
        page.keyboard.press("End")
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(2000)
        previous = len(found)
        links = page.get_by_role("link")
        for i in range(links.count()):
            try:
                loc = links.nth(i)
                txt = loc.inner_text(timeout=1000) or ""
                m = rx.search(txt)
                if not m:
                    continue
                href = loc.get_attribute("href")
                if href and "/lightning/r/" in href:
                    _k = m.group(0).strip()
                    if _k not in found:
                        found[_k] = href
            except Exception as e:  # noqa: BLE001
                print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
                continue
        idle = idle + 1 if len(found) <= previous else 0
    return found
