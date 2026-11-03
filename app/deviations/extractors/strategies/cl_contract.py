"""CL contract ref extraction from the opportunity page."""

from collections.abc import Callable

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.deviations.types import State

from .... import config as _c
from ...base import CL_CONTRACT_PRODUCT_MAP
from .. import opportunity
from .protocol import StrategyResult


class CLContractStrategy:
    name = "cl_contract"

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult:
        result = StrategyResult()
        product_cache = state.product_cache
        state.product_cache = product_cache
        for detail in state.details:
            if detail.skip:
                continue
            opp_url = detail.opportunity_url
            if not isinstance(opp_url, str) or not opp_url:
                continue
            if opp_url not in product_cache:
                page = session.require_page()
                if page.url != opp_url:
                    page = session.open(opp_url, wait=2)
                product_cache[opp_url] = opportunity.read_opportunity_product_type(session, opp_url)
            product_type = product_cache[opp_url]
            detail.opportunity_product_type = product_type
            target_product = CL_CONTRACT_PRODUCT_MAP.get(product_type) if product_type else None

            related_url = opp_url.replace("/view", "/related/CL_Contracts__r/view")
            tab = session.open_tab(related_url, wait=2)
            try:
                rows = tab.locator("tr.slds-hint-parent")
                contracts: list[tuple[str, str, str | None]] = []
                for i in range(rows.count()):
                    row = rows.nth(i)
                    cid = ""
                    href = ""
                    link_loc = row.get_by_role("link")
                    for j in range(link_loc.count()):
                        t = (link_loc.nth(j).inner_text(timeout=500) or "").strip()
                        h = link_loc.nth(j).get_attribute("href") or ""
                        if "LAI-" in t and h and "/lightning/r/" in h:
                            cid = t
                            href = h
                    prod_cell = row.locator('td[data-label="Product"], th[data-label="Product"]')
                    prod: str | None = None
                    if prod_cell.count() > 0:
                        prod = (prod_cell.first.inner_text(timeout=1000) or "").strip() or None
                    if cid and href:
                        contracts.append((href, cid, prod))

                matching = [
                    (href, cid)
                    for href, cid, prod in contracts
                    if target_product is None or prod == target_product
                ]

                if len(matching) > 1:
                    reason = (
                        f"skipped due to SF ambiguity: multiple matching CL contracts "
                        f"({len(matching)}) for {product_type} -> {target_product}"
                    )
                    detail.skip = True
                    detail.skip_reason = reason
                    state.skipped = state.skipped + 1
                    log(reason)
                    result.skip_reason = result.skip_reason or reason
                    continue
                if len(matching) == 1:
                    href, cid = matching[0]

                    abs_url = href if href.startswith("http") else f"{_c.ORG_BASE}{href}"
                    detail.refs = detail.refs + [
                        {"name": cid, "kind": "cl_contract", "url": abs_url}
                    ]
                    result.refs.append({"name": cid, "kind": "cl_contract", "url": abs_url})
                    log(f"cl_contract ref: {cid}")
                else:
                    log(f"no matching CL contract for {product_type} -> {target_product}")
            finally:
                try:
                    tab.close()
                except Exception as e:  # noqa: BLE001
                    print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
        return result
