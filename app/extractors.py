"""Extraction strategies for Salesforce Lightning list views."""
import re
from typing import Optional

from playwright.sync_api import Page

from . import config


def _text_matches(page, pattern: str):
    import re as _re
    return set(_re.findall(pattern, "\n".join(page.get_by_text(_re.compile(pattern)).all_text_contents())))


def collect_matches(page: Page, pattern: str, retries: int = 3):
    """Values matching `pattern` visible right now. Uses Playwright's text
    engine, which pierces Lightning's lockered LWC DOM (plain JS cannot)."""
    import re
    rx = re.compile(pattern)
    for attempt in range(retries):
        try:
            texts = page.get_by_text(rx).all_text_contents()
            return {m for t in texts for m in rx.findall(t)}
        except Exception:
            page.wait_for_timeout(1000)
    return set()


def read_item_total(page: Page) -> Optional[int]:
    """Parse N from the list header: '20 items • Sorted by ...'."""
    try:
        txt = page.get_by_text(re.compile(r"\d+\s+items?\s+[•·]")).first.inner_text()
        m = re.search(r"(\d+)\s+item", txt)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def wait_for_data(page: Page, pattern: str, timeout_s: float = 60) -> set:
    import time
    deadline = time.time() + timeout_s
    nums: set = set()
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        nums = collect_matches(page, pattern)
        if nums:
            return nums
    return nums


def extract_via_printable_view(page: Page, ctx, pattern: str) -> set:
    """Click 'Printable View'; popup renders ALL rows without virtualization."""
    try:
        btn = page.get_by_role("button", name="Printable View")
        if btn.count() == 0:
            return set()
        with ctx.expect_page(timeout=25_000) as popup_info:
            btn.first.click()
        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded", timeout=40_000)
        nums: set = set()
        stable = 0
        for _ in range(40):
            popup.wait_for_timeout(1500)
            batch = collect_matches(popup, pattern)
            if batch and batch == nums:
                stable += 1
            else:
                stable = 0
            nums |= batch
            if stable >= 3 and nums:
                break
        popup.close()
        return nums
    except Exception:
        return set()


def extract_via_scroll(page: Page, pattern: str, target: Optional[int] = None,
                       max_idle_rounds: int = 4) -> set:
    """Fallback: scroll the virtualized table until it stops yielding rows."""
    numbers: set = set()
    idle = 0
    rounds = 0
    while idle < max_idle_rounds:
        rounds += 1
        page.keyboard.press("End")
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(2500)
        from .extractors import collect_matches  # self-import safe
        new = collect_matches(page, pattern)
        added = len(new - numbers)
        numbers |= new
        if target is not None and len(numbers) >= target:
            break
        idle = idle + 1 if added == 0 else 0
    return numbers


def extract_list_view(sfsession, url: str, pattern: str, *, object_name: str = "records"):
    """Full strategy for one list-view URL. Returns (numbers, header_total).

    Raises SessionExpired if the injected session is no longer valid.
    """
    from .browser import SessionExpired

    page = sfsession.open(url, wait=4)
    if not _looks_logged_in(page):
        raise SessionExpired(f"not logged in for {url}")

    first = wait_for_data(page, pattern)
    total = read_item_total(page)
    numbers = extract_via_printable_view(page, sfsession.ctx, pattern)
    if not numbers:
        numbers = extract_via_scroll(page, pattern, target=total)
    return numbers, total


def _looks_logged_in(page: Page) -> bool:
    url = page.url
    return "/lightning/" in url and "login" not in url.lower()
