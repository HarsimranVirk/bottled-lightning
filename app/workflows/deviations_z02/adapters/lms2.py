"""LMS 2.0 CL contract and collateral discovery from the Opportunity page.

Both objects live behind a Lightning tab (``flexipage_tab2``) whose related list is a
custom component rendered in a shadow root, so the rows are read with one small JS helper
rather than text locators.
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from app.salesforce.adapters import (
    AdapterBase,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
)
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02.catalog import DeviationObject

from .dom import absolute_url

logger = logging.getLogger(__name__)

_LMS_TAB = 'a[data-tab-value="flexipage_tab2"]'


class _Lms2Adapter(AdapterBase):
    host_tag: str = ""
    detail_path: str = ""
    uuid_param: str = ""
    object_kind: str = ""

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
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

        if len(rows) > 1:
            return Discovery(
                skip_reason=(
                    "skipped due to SF ambiguity: multiple "
                    f"{self.object_kind.replace('_', ' ')} ({len(rows)})"
                )
            )
        if len(rows) == 1:
            row = rows[0]
            uuid = row.get("data_id") or ""
            if uuid:
                name = row.get("id_text") or uuid
                url = (
                    f"{self._org_base}/lightning/n/{self.detail_path}"
                    f"?c__{self.uuid_param}={uuid}"
                )
                return Discovery(
                    refs=(
                        DiscoveredRef(
                            kind=self.object_kind, name=name, url=url
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


class Lms2CollateralAdapter(_Lms2Adapter):
    kind = DeviationObject.LMS2_COLLATERAL.value
    object_kind = DeviationObject.LMS2_COLLATERAL.value
    host_tag = "c-lms-collateral-related-list"
    detail_path = "Collateral_Detail"
    uuid_param = "collateralId"


async def _open_lms_tab(page: Page, timeout_ms: int) -> None:
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
    try:
        await page.evaluate(
            "() => { const e = document.getElementById('auraError');"
            " if (e) e.remove(); }"
        )
    except Exception as exc:  # noqa: BLE001 - overlay removal is cosmetic
        logger.debug("auraError removal failed: %s", exc)


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
        result.push({data_id: dataId, id_text: idText});
    }
    return result;
}
"""


async def _await_lms_rows(
    page: Page, host_tag: str, timeout_ms: int
) -> list[dict[str, str]]:
    """The component renders after the tab click; poll until it produces rows."""
    waited = 0
    rows: list[dict[str, str]] = []
    while waited < timeout_ms:
        rows = await _scrape_lms_rows(page, host_tag)
        if rows:
            return rows
        await page.wait_for_timeout(1000)
        waited += 1000
    return rows


async def _scrape_lms_rows(page: Page, host_tag: str) -> list[dict[str, str]]:
    try:
        raw: object = await page.evaluate(_LMS_ROWS_JS, host_tag)
    except Exception as exc:  # noqa: BLE001 - component not rendered
        logger.debug("LMS row scrape failed for %s: %s", host_tag, exc)
        return []
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        data_id = item.get("data_id")
        id_text = item.get("id_text")
        rows.append(
            {
                "data_id": data_id if isinstance(data_id, str) else "",
                "id_text": id_text if isinstance(id_text, str) else "",
            }
        )
    return rows
