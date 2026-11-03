"""Shared extraction helpers (Playwright text-engine based)."""

import re
import time

from playwright.sync_api import Page


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
    def grab(rx: str) -> str | None:
        m = re.search(rx, description, re.MULTILINE)
        return m.group(1).strip() or None if m else None

    return {
        "property_value": grab(r"(?m)^\s*Property Value[^-\n]*-\s?(.+)$"),
        "loan_amount": grab(r"(?m)^\s*Loan Amount[^-\n]*-\s?(.+)$"),
        "tenure": grab(r"(?m)^\s*Tenure[^-\n]*-\s?(.+)$"),
        "emi": grab(r"(?m)^\s*EMIs?\s*&[^-\n]*-\s?(.+)$"),
    }


def clean_description(raw: str) -> str:
    drop = (
        r"^\s*(Help |Edit |)?Loan Deviation Description\s*$",
        r"^\s* Help Loan Deviation Description\s*$",
    )
    lines = raw.splitlines()
    lines = [ln for ln in lines if not any(re.match(pat, ln, re.IGNORECASE) for pat in drop)]
    return "\n".join(lines).strip()


def looks_logged_in(page: Page) -> bool:
    url = page.url
    return "/lightning/" in url and "login" not in url.lower()
