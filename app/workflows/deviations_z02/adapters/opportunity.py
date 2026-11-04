"""Opportunity page: product type (drives CL-contract matching)."""

from __future__ import annotations

from app.salesforce.adapters import AdapterBase, Discovery, DiscoveryContext
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02.catalog import DeviationObject

from .dom import absolute_url, safe_body_text


def product_type_from(body: str) -> str | None:
    """Pull the value Salesforce renders under the "Product Type" label."""
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "Product Type":
            continue
        for candidate in range(index + 1, min(index + 4, len(lines))):
            value = lines[candidate].strip()
            if value:
                return value
    return None


class OpportunityAdapter(AdapterBase):
    kind = DeviationObject.OPPORTUNITY.value

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        if not context.opportunity_url:
            return Discovery()
        page = await tabs.new_page(absolute_url(context.opportunity_url, self._org_base))
        try:
            body = await safe_body_text(page)
            return Discovery(
                attributes={"product_type": product_type_from(body or "")}
            )
        finally:
            await tabs.close_page(page)
