"""LMS 2.0 CL contract and collateral: discovery and editable values.

Both objects live behind a Lightning tab (``flexipage_tab2``) whose related list is a
custom component rendered in a shadow root, so extraction reads rows with one small JS
helper. A loan legitimately has several LMS 2.0 CL contracts, so the CL-contract variant
is narrowed by the same product mapping as the regular CL-contract related list; only two
rows matching the *target* product are ambiguous.

Submission edits the custom detail pages: the collateral page's Edit form (Financials →
Property Value) and the CL contract page's LOAN QUICK ACTIONS → Contract Modification
form (Loan amount / Tenure cards). Both pages are LWC shadow DOM, so all locators go
through Playwright's shadow-piercing engine and never through ``page.evaluate``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial

from playwright.async_api import Locator, Page

from app.core.field import FieldTarget, ValueType, normalise
from app.core.status import WriteOutcome
from app.salesforce.adapters import (
    AdapterBase,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
)
from app.salesforce.tabs import TabProvider
from app.utils.dom import (
    absolute_url,
    click_first_visible,
    poll,
    safe_inner_text,
)
from app.workflows.deviations_z02.catalog import DeviationObject
from app.workflows.deviations_z02.product_map import CL_CONTRACT_PRODUCT_MAP

logger = logging.getLogger(__name__)

_LMS_TAB = 'a[data-tab-value="flexipage_tab2"]'
_COLLATERAL_PROPERTY_FIELD = "propertyValue"
_CONTRACT_FIELD_BY_SECTION: Mapping[str, str] = {
    "Loan amount": "loanAmount",
    "Tenure": "tenure",
}


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


def _same_amount(raw: str | None, intended: str) -> bool:
    """Whether a displayed amount canonicalises to the intended amount."""
    if raw is None:
        return False
    try:
        return normalise(raw, ValueType.AMOUNT) == normalise(intended, ValueType.AMOUNT)
    except ValueError:
        return raw.strip() == intended.strip()


def _tenure_months(raw: str | None) -> str | None:
    """Turn the LMS 2.0 ``180 months`` display into the canonical month count."""
    if raw is None:
        return None
    text = raw.strip().lower().removesuffix("months").strip()
    return text or None


class _Lms2Adapter(AdapterBase):
    """Shared discovery for the two LMS 2.0 related lists."""

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
    """LMS 2.0 CL contract: editable through Contract Modification."""

    kind = DeviationObject.LMS2_CL_CONTRACT.value
    object_kind = DeviationObject.LMS2_CL_CONTRACT.value
    host_tag = "c-lms-cl-contract-related-list"
    detail_path = "CL_Contract_Detail"
    uuid_param = "loanId"
    matches_product = True

    async def read(
        self, page: Page, targets: Sequence[FieldTarget]
    ) -> dict[FieldTarget, str | None]:
        """Read the Contract Modification form's CURRENT values."""
        values: dict[FieldTarget, str | None] = {}
        try:
            if not await self._open_modification(page):
                return {target: None for target in targets}
            for target in targets:
                card = await self._card(page, target)
                if card is None:
                    values[target] = None
                    continue
                raw = await safe_inner_text(
                    card.locator(".mod-current-value").first, self._timeout_ms
                )
                values[target] = (
                    _tenure_months(raw) if target.section == "Tenure" else raw
                )
        finally:
            await self._cancel_modification(page)
        return values

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str]
    ) -> dict[FieldTarget, WriteOutcome]:
        """Fill the Loan amount and Tenure cards, then Save Changes."""
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        if not await self._open_modification(page):
            return {target: WriteOutcome.UNKNOWN for target in values}
        try:
            for target, value in values.items():
                card = await self._card(page, target)
                if card is None:
                    outcomes[target] = WriteOutcome.UNKNOWN
                    continue
                await card.locator("input").first.fill(value)
                outcomes[target] = WriteOutcome.SAVED
            save = page.get_by_role("button", name="Save Changes", exact=True)
            if not await click_first_visible(save, self._timeout_ms):
                return {target: WriteOutcome.UNKNOWN for target in values}
            closed = await poll(
                lambda: self._form_closed(page), self._timeout_ms
            )
            if not closed:
                return {target: WriteOutcome.REJECTED for target in values}
            return outcomes
        except Exception as exc:  # noqa: BLE001 - page may re-render mid-save
            logger.debug("lms cl-contract write failed: %s", exc)
            return {target: WriteOutcome.UNKNOWN for target in values}
        finally:
            await self._cancel_modification(page)

    async def _card(self, page: Page, target: FieldTarget) -> Locator | None:
        """The Contract Modification card for a target (Loan amount or Tenure)."""
        data_field = _CONTRACT_FIELD_BY_SECTION.get(target.section or "")
        if data_field is None:
            return None
        card = page.locator("div.mod-card").filter(
            has=page.locator(f'lightning-input[data-field="{data_field}"]')
        ).first
        ready = await poll(lambda: _has_count(card, 1), self._timeout_ms)
        return card if ready else None

    async def _open_modification(self, page: Page) -> bool:
        """Expand LOAN QUICK ACTIONS and open the Contract Modification form."""
        if await page.locator("div.mod-shell").count() > 0:
            return True
        trigger = page.locator('button.nav-section-trigger[data-group="loanactions"]')
        if not await poll(lambda: _has_count(trigger, 1), self._timeout_ms):
            return False
        if await trigger.count() > 0:
            try:
                if await trigger.first.get_attribute("aria-expanded") != "true":
                    await trigger.first.click(timeout=self._timeout_ms)
            except Exception as exc:  # noqa: BLE001 - already expanded
                logger.debug("lms loanactions expand failed: %s", exc)
        item = page.locator('button.nav-item[data-tab="contractMod"]')
        if await item.count() == 0:
            return False
        try:
            await item.first.click(timeout=self._timeout_ms)
        except Exception as exc:  # noqa: BLE001 - overlay may intercept
            logger.debug("lms contract-modification click failed: %s", exc)
            return False
        return await poll(
            lambda: _has_count(page.locator("div.mod-shell"), 1), self._timeout_ms
        )

    async def _cancel_modification(self, page: Page) -> None:
        """Close the Contract Modification form without saving."""
        cancel = page.get_by_role("button", name="Cancel", exact=True)
        if await cancel.count() > 0:
            try:
                await cancel.first.click(timeout=5000)
                await poll(lambda: self._form_closed(page), 5000)
            except Exception as exc:  # noqa: BLE001 - form may already be closed
                logger.debug("lms contract-modification cancel failed: %s", exc)

    async def _form_closed(self, page: Page) -> bool:
        """Whether the Contract Modification shell has gone."""
        return await page.locator("div.mod-shell").count() == 0


class Lms2CollateralAdapter(_Lms2Adapter):
    """LMS 2.0 collateral: editable through the page's Edit/Save form."""

    kind = DeviationObject.LMS2_COLLATERAL.value
    object_kind = DeviationObject.LMS2_COLLATERAL.value
    host_tag = "c-lms-collateral-related-list"
    detail_path = "Collateral_Detail"
    uuid_param = "collateralId"

    async def read(
        self, page: Page, targets: Sequence[FieldTarget]
    ) -> dict[FieldTarget, str | None]:
        """Read Property Value from the Financials card (view or edit mode)."""
        values: dict[FieldTarget, str | None] = {}
        for target in targets:
            raw = await self._read_view(page, target)
            if raw is None:
                input_locator = page.locator(
                    f'lightning-input[data-field="{_COLLATERAL_PROPERTY_FIELD}"] input'
                )
                if await input_locator.count() > 0:
                    raw = await input_locator.first.input_value()
            values[target] = raw
        return values

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str]
    ) -> dict[FieldTarget, WriteOutcome]:
        """Click Edit, fill Property Value, click Save and verify the read-back."""
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        edit = page.get_by_role("button", name="Edit", exact=True)
        if not await click_first_visible(edit, self._timeout_ms):
            return {target: WriteOutcome.UNKNOWN for target in values}
        input_locator = page.locator(
            f'lightning-input[data-field="{_COLLATERAL_PROPERTY_FIELD}"] input'
        )
        if not await poll(lambda: _has_count(input_locator, 1), self._timeout_ms):
            return {target: WriteOutcome.UNKNOWN for target in values}
        try:
            for target, value in values.items():
                await input_locator.first.fill(value)
                outcomes[target] = WriteOutcome.SAVED
            save = page.get_by_role("button", name="Save", exact=True)
            if not await click_first_visible(save, self._timeout_ms):
                return {target: WriteOutcome.UNKNOWN for target in values}
            for target, value in values.items():
                saved = await poll(
                    partial(self._saved, page, target, value),
                    self._timeout_ms,
                )
                outcomes[target] = (
                    WriteOutcome.SAVED if saved else WriteOutcome.REJECTED
                )
            return outcomes
        except Exception as exc:  # noqa: BLE001 - page may re-render mid-save
            logger.debug("lms collateral write failed: %s", exc)
            return {target: WriteOutcome.UNKNOWN for target in values}

    async def _read_view(self, page: Page, target: FieldTarget) -> str | None:
        """Read the Financials stat value in view mode."""
        stat = page.locator("div.stat-item").filter(has_text=target.label).first
        if not await poll(lambda: _has_count(stat, 1), self._timeout_ms):
            return None
        value = stat.locator(".stat-value").first
        if not await poll(lambda: _has_count(value, 1), 10_000):
            return None
        return await safe_inner_text(value, 2000)

    async def _saved(self, page: Page, target: FieldTarget, value: str) -> bool:
        """Whether the view-mode stat reads back the intended amount."""
        raw = await self._read_view(page, target)
        return _same_amount(raw, value)


async def _has_count(locator: Locator, minimum: int) -> bool:
    """Whether a locator currently matches at least ``minimum`` elements."""
    return await locator.count() >= minimum


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
