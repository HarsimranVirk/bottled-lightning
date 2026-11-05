"""CL contract discovery and the editable Contract/Funding fields.

The CL-contract record is a Classic Visualforce page (``tabbedLoanAccount``) embedded in
an iframe on the Lightning record page. The iframe URL is reachable directly through the
org's Classic host, so submission opens ``https://<org>.my.salesforce.com/<record-id>``
and edits the Classic inline-edit cells (double-click, fill, Save). This avoids the
Lightning wrapper page, which is not required to write the values.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from playwright.async_api import Locator, Page

from app.core.field import FieldTarget, ValueType, normalise
from app.core.models import PageRef
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
    related_list_url,
    safe_inner_text,
    wait_for_rows,
)
from app.workflows.deviations_z02.catalog import DeviationObject
from app.workflows.deviations_z02.product_map import CL_CONTRACT_PRODUCT_MAP

logger = logging.getLogger(__name__)

_RELATED_LIST = "CL_Contracts__r"
_CONTRACT_PREFIX = "LAI-"
_TENURE_LABEL = "Term"


def _classic_base(org_base: str) -> str:
    """The org's Classic host, used for the Visualforce page behind the iframe."""
    if ".lightning.force.com" in org_base:
        return org_base.replace(".lightning.force.com", ".my.salesforce.com")
    return org_base


def _record_id(url: str) -> str | None:
    """
    Extract the record id from a Lightning record URL.

    Both URL shapes occur in this org: ``/lightning/r/<id>/view`` (custom objects) and
    ``/lightning/r/<Object>/<id>/view`` (standard objects). The id is always the segment
    immediately before the final ``view`` segment.
    """
    clean = url.split("?", 1)[0].rstrip("/")
    marker = "/lightning/r/"
    if marker not in clean:
        return None
    parts = clean.split(marker, 1)[1].split("/")
    if len(parts) >= 2 and parts[-1] == "view":
        return parts[-2] or None
    return None


def _value_type(target: FieldTarget) -> ValueType:
    """The storage type of a target on this page (only Term is months)."""
    return ValueType.TENURE_MONTHS if target.label == _TENURE_LABEL else ValueType.AMOUNT


def _same(target: FieldTarget, raw: str | None, intended: str) -> bool:
    """Whether a Classic cell value canonicalises to the intended value."""
    if raw is None:
        return False
    value_type = _value_type(target)
    try:
        return normalise(raw, value_type) == normalise(intended, value_type)
    except ValueError:
        return raw.strip() == intended.strip()


async def _has_input(cell: Locator) -> bool:
    """Whether the Classic cell is in inline-edit mode."""
    return await cell.locator("input").count() > 0


async def _has_labels(page: Page) -> bool:
    """Whether the Classic page has rendered its field table."""
    return await page.locator("td.labelCol").count() > 0


class ClContractAdapter(AdapterBase):
    """
    CL contract link for the opportunity's matching product.

    Extraction reads the ``CL_Contracts__r`` related list and keeps the contract whose
    Product column matches the mapped opportunity product. Submission edits the same
    contract's Loan Amount (Contract), Term (Contract) and Financed Amount (Funding)
    through the Classic inline-edit cells.
    """

    kind = DeviationObject.CL_CONTRACT.value

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        """Store org base, Classic host and page timeout."""
        self._org_base = org_base
        self._classic_base = _classic_base(org_base)
        self._timeout_ms = timeout_ms

    async def open(self, tabs: TabProvider, ref: PageRef) -> Page:
        """Open the Classic Visualforce page that holds the editable cells."""
        record_id = _record_id(ref.url)
        url = f"{self._classic_base}/{record_id}" if record_id else ref.url
        return await tabs.new_page(url)

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

    async def read(
        self, page: Page, targets: Sequence[FieldTarget]
    ) -> dict[FieldTarget, str | None]:
        """Read the Classic cells for the requested targets."""
        await poll(lambda: _has_labels(page), self._timeout_ms)
        values: dict[FieldTarget, str | None] = {}
        for target in targets:
            cell = await self._value_cell(page, target)
            if cell is None:
                values[target] = None
                continue
            values[target] = await safe_inner_text(cell, self._timeout_ms)
        return values

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str]
    ) -> dict[FieldTarget, WriteOutcome]:
        """Inline-edit and save each Classic cell, returning per-target outcomes."""
        await poll(lambda: _has_labels(page), self._timeout_ms)
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        for target, value in values.items():
            cell = await self._value_cell(page, target)
            if cell is None:
                outcomes[target] = WriteOutcome.UNKNOWN
                continue
            outcomes[target] = await self._edit(page, cell, target, value)
        return outcomes

    async def _label_cell(self, page: Page, target: FieldTarget) -> Locator | None:
        """Find the ``td.labelCol`` for a target, scoping by section if repeated."""
        matches = await _matching_labels(page.locator("td.labelCol"), target.label)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1 and target.section is not None:
            header = page.get_by_text(target.section, exact=True).first
            if await header.count() > 0:
                table = header.locator("xpath=ancestor::table[1]")
                if await table.count() > 0:
                    scoped = await _matching_labels(
                        table.locator("td.labelCol"), target.label
                    )
                    if scoped:
                        return scoped[0]
        return matches[0] if matches else None

    async def _value_cell(self, page: Page, target: FieldTarget) -> Locator | None:
        """The value cell immediately following a target's label cell."""
        label = await self._label_cell(page, target)
        if label is None:
            return None
        cell = label.locator("xpath=following-sibling::td[1]")
        return cell.first if await cell.count() > 0 else None

    async def _edit(
        self, page: Page, cell: Locator, target: FieldTarget, value: str
    ) -> WriteOutcome:
        """Double-click the cell, fill it, save and verify the read-back."""
        try:
            await cell.dblclick(timeout=self._timeout_ms)
            if not await poll(lambda: _has_input(cell), self._timeout_ms):
                return WriteOutcome.UNKNOWN
            await cell.locator("input").first.fill(value)
            save = page.locator('input[name="inlineEditSave"]')
            if not await click_first_visible(save, self._timeout_ms):
                return WriteOutcome.UNKNOWN
            if not await poll(
                lambda: self._saved(page, target, value), self._timeout_ms
            ):
                return WriteOutcome.REJECTED
            return WriteOutcome.SAVED
        except Exception as exc:  # noqa: BLE001 - Classic AJAX may replace the cell
            logger.debug("cl-contract write failed for %s: %s", target, exc)
            return WriteOutcome.UNKNOWN

    async def _saved(self, page: Page, target: FieldTarget, value: str) -> bool:
        """Whether the cell left edit mode and reads back the intended value."""
        cell = await self._value_cell(page, target)
        if cell is None or await _has_input(cell):
            return False
        raw = await safe_inner_text(cell, 2000)
        return _same(target, raw, value)


async def _matching_labels(labels: Locator, text: str) -> list[Locator]:
    """All label cells whose trimmed text equals ``text``."""
    found: list[Locator] = []
    for index in range(await labels.count()):
        cell = labels.nth(index)
        current = await safe_inner_text(cell, 1000)
        if current == text:
            found.append(cell)
    return found


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
