"""Shared extraction helpers (Playwright text-engine based)."""

import re
import time

from playwright.sync_api import Page

from app.workflows.deviations_z02.description import (
    clean_description as _clean_v2,
)
from app.workflows.deviations_z02.description import (
    parse_description_fields as _parse_v2,
)


def collect_matches(page: Page, pattern: str, retries: int = 3) -> set[str]:
    rx = re.compile(pattern)
    for _attempt in range(retries):
        try:
            texts = page.get_by_text(rx).all_text_contents()
            return {m for t in texts for m in rx.findall(t)}
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(1000)
    return set()


def read_item_total(page: Page) -> int | None:
    try:
        txt = page.get_by_text(re.compile(r"\d+\s+items?\s+[•·]")).first.inner_text()
        m = re.search(r"(\d+)\s+item", txt)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def wait_for_data(page: Page, pattern: str, timeout_s: float = 60) -> set[str]:
    deadline = time.time() + timeout_s
    nums: set[str] = set()
    while time.time() < deadline:
        page.wait_for_timeout(1500)
        nums = collect_matches(page, pattern)
        if nums:
            return nums
    return nums


def click_show_more(page: Page, max_clicks: int = 300) -> int:
    more_rx = re.compile(r"^\s*Show more\s*$", re.IGNORECASE)
    clicked = 0
    while clicked < max_clicks:
        locators = [
            page.get_by_role("button", name=more_rx),
            page.get_by_text(more_rx),
        ]
        more = None
        for loc in locators:
            try:
                if loc.count() > 0:
                    more = loc.first
                    break
            except Exception as e:  # noqa: BLE001
                print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
                continue
        if more is None:
            break
        try:
            more.click(timeout=5000)
            clicked += 1
            page.wait_for_timeout(2000)
        except Exception:  # noqa: BLE001
            break
    return clicked


def parse_description_fields(description: str) -> dict[str, str | None]:
    """Legacy shape (``emi`` key) over the v2 parser.

    Single implementation lives in ``app/workflows/deviations_z02/description.py``; the
    mapping below keeps the pre-refactor extractors working until they are deleted.
    """
    parsed = _parse_v2(description)
    return {
        "property_value": parsed["property_value"],
        "loan_amount": parsed["loan_amount"],
        "tenure": parsed["tenure"],
        "emi": parsed["emi_incl_hffc"],
    }


def clean_description(raw: str) -> str:
    return _clean_v2(raw)


def looks_logged_in(page: Page) -> bool:
    url = page.url
    return "/lightning/" in url and "login" not in url.lower()
