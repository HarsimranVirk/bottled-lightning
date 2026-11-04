"""Collateral discovery: the related list on the Opportunity."""

from __future__ import annotations

from playwright.async_api import Locator

from app.salesforce.adapters import (
    AdapterBase,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
)
from app.salesforce.tabs import TabProvider
from app.utils.dom import absolute_url, related_list_url, safe_inner_text, wait_for_rows
from app.workflows.deviations_z02.catalog import DeviationObject

_RELATED_LIST = "Collateral__r"


class CollateralAdapter(AdapterBase):
    """Collateral link for the opportunity."""

    kind = DeviationObject.COLLATERAL.value

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        """Store org base and page timeout."""
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        """Find the single collateral attached to the opportunity."""
        if not context.opportunity_url:
            return Discovery()
        url = related_list_url(
            absolute_url(context.opportunity_url, self._org_base), _RELATED_LIST
        )
        page = await tabs.new_page(url)
        try:
            rows = page.locator("tr.slds-hint-parent")
            count = await wait_for_rows(rows, page, self._timeout_ms)
            if count > 1:
                return Discovery(
                    skip_reason=(
                        "skipped due to SF ambiguity: "
                        f"multiple collateral objects ({count})"
                    )
                )
            if count == 1:
                ref = await _first_collateral(rows.nth(0), self._org_base)
                if ref is not None:
                    return Discovery(refs=(ref,))
            return Discovery()
        finally:
            await tabs.close_page(page)


async def _first_collateral(row: Locator, org_base: str) -> DiscoveredRef | None:
    """Extract the ref from one related-list row."""
    cid = ""
    href = ""
    links = row.get_by_role("link")
    for index in range(await links.count()):
        locator = links.nth(index)
        text = await safe_inner_text(locator, 500) or ""
        candidate = await locator.get_attribute("href") or ""
        if candidate and "/lightning/r/" in candidate:
            cid = text or cid
            href = candidate
    if not href:
        return None
    return DiscoveredRef(
        kind=DeviationObject.COLLATERAL.value,
        name=cid or href,
        url=absolute_url(href, org_base),
    )
