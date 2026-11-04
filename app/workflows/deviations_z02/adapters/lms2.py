"""LMS 2.0 CL contract and collateral discovery from the Opportunity page.

Both objects live behind a Lightning tab (``flexipage_tab2``) whose related list is a
custom component rendered in a shadow root, so rows are read with one small JS helper.
A loan legitimately has several LMS 2.0 CL contracts, so the CL-contract variant is
narrowed by the same product mapping as the regular CL-contract related list; only two
rows matching the *target* product are ambiguous.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from playwright.async_api import Page

from app.salesforce.adapters import (
    AdapterBase,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
)
from app.salesforce.tabs import TabProvider
from app.utils.dom import absolute_url
from app.workflows.deviations_z02.catalog import DeviationObject
from app.workflows.deviations_z02.product_map import CL_CONTRACT_PRODUCT_MAP

logger = logging.getLogger(__name__)

_LMS_TAB = 'a[data-tab-value="flexipage_tab2"]'


@dataclass(frozen=True, slots=True)
class LmsRow:
    """One row of an LMS 2.0 related list."""

    data_id: str
    name: str
    cells: tuple[str, ...]


def match_rows(rows: Sequence[LmsRow], target: str | None) -> list[LmsRow]:
    """Rows whose cell text equals the target product.

    With no target every row is a candidate, which keeps the old "cannot disambiguate"
    behaviour when the opportunity product is unknown. Exact cell equality avoids
    matching ``Home Loan Resale`` when the target is ``Home Loan``.
    """
    if target is None:
        return list(rows)
    return [row for row in rows if target in row.cells]


class _Lms2Adapter(AdapterBase):
    host_tag: str = ""
    detail_path: str = ""
    uuid_param: str = ""
    object_kind: str = ""
    matches_product: bool = False

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        """Store org base and page timeout."""
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        """Open the LMS tab on the opportunity and pick the matching row."""
        if not context.opportunity_url:
            return Discovery()
        page = await tabs.new_page(
            absolute_url(context.opportunity_url, self._org_base)
        )
        try:
            await _open_lms_tab(page, self._timeout_ms)
            rows = await _await_lms_rows(page, self.host_tag, self._timeout_ms)
        finally:
            await tabs.close_page(page)

        target = None
        if self.matches_product and context.product_type:
            target = CL_CONTRACT_PRODUCT_MAP.get(context.product_type)
        candidates = match_rows(rows, target) if self.matches_product else list(rows)

        label = self.object_kind.replace("_", " ")
        if len(candidates) > 1:
            detail = (
                f" for {context.product_type} -> {target}" if target is not None else ""
            )
            return Discovery(
                skip_reason=(
                    f"skipped due to SF ambiguity: multiple {label} "
                    f"({len(candidates)}){detail}"
                )
            )
        if len(candidates) == 1:
            row = candidates[0]
            if row.data_id:
                url = (
                    f"{self._org_base}/lightning/n/{self.detail_path}"
                    f"?c__{self.uuid_param}={row.data_id}"
                )
                return Discovery(
                    refs=(
                        DiscoveredRef(
                            kind=self.object_kind,
                            name=row.name or row.data_id,
                            url=url,
                        ),
                    )
                )
        return Discovery()


class Lms2ClContractAdapter(_Lms2Adapter):
    kind = DeviationObject.LMS2_CL_CONTRACT.value
    object_kind = DeviationObject.LMS2_CL_CONTRACT.value
    host_tag = "c-lms-cl-contract-related-list"
    detail_path = "CL_Contract_Detail"
    uuid_param = "loanId"
    matches_product = True


class Lms2CollateralAdapter(_Lms2Adapter):
    kind = DeviationObject.LMS2_COLLATERAL.value
    object_kind = DeviationObject.LMS2_COLLATERAL.value
    host_tag = "c-lms-collateral-related-list"
    detail_path = "Collateral_Detail"
    uuid_param = "collateralId"


async def _open_lms_tab(page: Page, timeout_ms: int) -> None:
    """Wait for and click the LMS tab on the opportunity page."""
    tab = page.locator(_LMS_TAB)
    waited = 0
    while waited < timeout_ms:
        if await tab.count() > 0:
            break
        await page.wait_for_timeout(500)
        waited += 500
    try:
        if await tab.count() > 0 and await tab.first.get_attribute("aria-selected") != "true":
            await tab.first.click(timeout=5000)
            await page.wait_for_timeout(1000)
    except Exception as exc:  # noqa: BLE001 - tab may already be open
        logger.debug("LMS tab click failed: %s", exc)


_LMS_ROWS_JS = """
(hostTag) => {
    const result = [];
    function findHost(tag, root) {
        const found = root.querySelector ? root.querySelector(tag) : null;
        if (found) return found;
        const els = root.querySelectorAll ? root.querySelectorAll('*') : [];
        for (const el of els) {
            if (el.shadowRoot) {
                const r = findHost(tag, el.shadowRoot);
                if (r) return r;
            }
        }
        return null;
    }
    const host = findHost(hostTag, document);
    if (!host || !host.shadowRoot) return result;
    const root = host.shadowRoot;
    const rowEls = root.querySelectorAll('tr.rl-row, tr.data-row, div.contract-row, div.rl-row');
    for (const r of rowEls) {
        const dataId = r.getAttribute('data-id') || '';
        let idText = '';
        const idEl = r.querySelector('span.id-link, span.loan-link');
        if (idEl) idText = (idEl.textContent || '').trim();
        const cells = Array.from(r.children).map((el) => (el.textContent || '').trim());
        result.push({data_id: dataId, id_text: idText, cells: cells});
    }
    return result;
}
"""


async def _await_lms_rows(page: Page, host_tag: str, timeout_ms: int) -> list[LmsRow]:
    """The component renders after the tab click; poll until it produces rows."""
    waited = 0
    rows: list[LmsRow] = []
    while waited < timeout_ms:
        rows = await _scrape_lms_rows(page, host_tag)
        if rows:
            return rows
        await page.wait_for_timeout(1000)
        waited += 1000
    return rows


async def _scrape_lms_rows(page: Page, host_tag: str) -> list[LmsRow]:
    """Read rows from the component's shadow root."""
    try:
        # Playwright's evaluate() is typed Any; narrow immediately with isinstance.
        raw = await page.evaluate(_LMS_ROWS_JS, host_tag)
    except Exception as exc:  # noqa: BLE001 - component not rendered
        logger.debug("LMS row scrape failed for %s: %s", host_tag, exc)
        return []
    if not isinstance(raw, list):
        return []
    rows: list[LmsRow] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        data_id = item.get("data_id")
        name = item.get("id_text")
        cells_raw = item.get("cells")
        cells: tuple[str, ...] = ()
        if isinstance(cells_raw, list):
            cells = tuple(cell for cell in cells_raw if isinstance(cell, str))
        rows.append(
            LmsRow(
                data_id=data_id if isinstance(data_id, str) else "",
                name=name if isinstance(name, str) else "",
                cells=cells,
            )
        )
    return rows
