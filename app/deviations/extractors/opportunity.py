"""Opportunity-page context + ref extraction (composite collector)."""

from app.browser import SalesforceSession

from .common import looks_logged_in


def read_opportunity_product_type(session: SalesforceSession, opportunity_url: str) -> str | None:
    page = session.require_page()
    if page.url != opportunity_url:
        page = session.open(opportunity_url, wait=2)
    if not looks_logged_in(page):
        return None
    try:
        body: str = page.locator("body").inner_text(timeout=10000)
    except Exception:  # noqa: BLE001
        return None
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "Product Type":
            # value is the next non-empty line (skip blanks)
            for j in range(i + 1, min(i + 4, len(lines))):
                val = lines[j].strip()
                if val:
                    return val
    return None
