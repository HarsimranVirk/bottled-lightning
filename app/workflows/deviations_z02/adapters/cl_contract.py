"""CL contract discovery: the related list on the Opportunity, matched by product."""

from __future__ import annotations

from playwright.async_api import Page

from app.salesforce.adapters import (
    AdapterBase,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
)
from app.salesforce.tabs import TabProvider
from app.utils.dom import absolute_url, related_list_url, safe_inner_text, wait_for_rows
from app.workflows.deviations_z02.catalog import DeviationObject
from app.workflows.deviations_z02.product_map import CL_CONTRACT_PRODUCT_MAP

_RELATED_LIST = "CL_Contracts__r"
_CONTRACT_PREFIX = "LAI-"


class ClContractAdapter(AdapterBase):
    """CL contract link for the opportunity's matching product."""

    kind = DeviationObject.CL_CONTRACT.value

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        """Store org base and page timeout."""
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        """Find the single CL contract matching the opportunity product."""
        if not context.opportunity_url:
            return Discovery()
        url = related_list_url(
            absolute_url(context.opportunity_url, self._org_base), _RELATED_LIST
        )
        page = await tabs.new_page(url)
        try:
            await wait_for_rows(page.locator("tr.slds-hint-parent"), page, self._timeout_ms)
            contracts = await _contracts(page)
        finally:
            await tabs.close_page(page)

        target = (
            CL_CONTRACT_PRODUCT_MAP.get(context.product_type)
            if context.product_type
            else None
        )
        matching = [
            (href, cid)
            for href, cid, product in contracts
            if target is None or product == target
        ]
        if len(matching) > 1:
            return Discovery(
                skip_reason=(
                    "skipped due to SF ambiguity: multiple matching CL contracts "
                    f"({len(matching)}) for {context.product_type} -> {target}"
                )
            )
        if len(matching) == 1:
            href, cid = matching[0]
            return Discovery(
                refs=(
                    DiscoveredRef(
                        kind=DeviationObject.CL_CONTRACT.value,
                        name=cid,
                        url=absolute_url(href, self._org_base),
                    ),
                )
            )
        return Discovery()


async def _contracts(page: Page) -> list[tuple[str, str, str | None]]:
    """Parse (href, id, product) triples from the related list."""
    rows = page.locator("tr.slds-hint-parent")
    found: list[tuple[str, str, str | None]] = []
    for index in range(await rows.count()):
        row = rows.nth(index)
        cid = ""
        href = ""
        links = row.get_by_role("link")
        for link_index in range(await links.count()):
            locator = links.nth(link_index)
            text = await safe_inner_text(locator, 500) or ""
            candidate = await locator.get_attribute("href") or ""
            if _CONTRACT_PREFIX in text and candidate and "/lightning/r/" in candidate:
                cid = text
                href = candidate
        product = None
        cell = row.locator('td[data-label="Product"], th[data-label="Product"]')
        if await cell.count() > 0:
            product = await safe_inner_text(cell.first, 1000)
        if cid and href:
            found.append((href, cid, product))
    return found
