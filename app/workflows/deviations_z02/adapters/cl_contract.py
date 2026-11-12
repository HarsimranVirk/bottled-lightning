"""CL contract discovery and the editable Contract/Funding fields.

The CL-contract record is a Lightning ``loan__Loan_Account__c`` page that embeds the
Classic Visualforce form (``tabbedLoanAccount``) in a ``vfFrameId_*`` iframe. Submission
opens the Lightning ref URL directly and resolves that iframe. The top-level Classic
fallback remains for a ref that is already a Classic URL. The fields are Classic
inline-edit cells (double-click, fill, Save) inside the resolved frame.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from functools import partial

from playwright.async_api import Frame, Locator, Page

from app.core.field import FieldTarget, ValueType, normalise
from app.core.job_logger import JobLogger
from app.core.models import PageRef
from app.core.status import WriteOutcome
from app.salesforce.adapters import (
    AdapterBase,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
    absent,
    describe_target,
    unresolved,
)
from app.salesforce.tabs import TabProvider
from app.utils.dom import (
    Deadline,
    absolute_url,
    bounded,
    clear_and_fill,
    click_first_visible,
    poll,
    related_list_empty,
    related_list_url,
    safe_inner_text,
    settled_row_count,
)
from app.workflows.deviations_z02.catalog import DeviationObject
from app.workflows.deviations_z02.product_map import CL_CONTRACT_PRODUCT_MAP

logger = logging.getLogger(__name__)

_RELATED_LIST = "CL_Contracts__r"
_CONTRACT_PREFIX = "LAI-"
_TENURE_LABEL = "Term"


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


async def _form_frame(page: Page, timeout_ms: int) -> Frame | None:
    """
    The frame that actually holds the Classic field table.

    The Lightning ref redirects to the ``loan__Loan_Account__c`` record page and embeds
    the Classic form in a ``tabbedLoanAccount`` iframe. A ref that is already a Classic
    URL may serve the table top-level. Return the top-level frame when it has the labels;
    otherwise wait for the iframe and return that. Every wait uses a monotonic deadline.
    """
    deadline = Deadline(timeout_ms)
    while not deadline.expired:
        try:
            if await bounded(page.locator("td.labelCol").count, deadline) > 0:
                return page.main_frame
        except TimeoutError:
            return None
        for frame in page.frames:
            if "tabbedLoanAccount" not in frame.url:
                continue
            try:
                count = await bounded(frame.locator("td.labelCol").count, deadline)
            except TimeoutError:
                return None
            except Exception as exc:  # noqa: BLE001 - frame may still be loading
                logger.debug("CL contract frame check failed: %s", exc)
                continue
            if count > 0:
                return frame
        await page.wait_for_timeout(max(0, min(500, deadline.remaining_ms())))
    return None


class ClContractAdapter(AdapterBase):
    """
    CL contract link for the opportunity's matching product.

    Extraction reads the ``CL_Contracts__r`` related list and keeps the contract whose
    Product column matches the mapped opportunity product. Submission opens the Lightning
    ref URL and edits the same contract's Loan Amount (Contract), Term (Contract) and
    Financed Amount (Funding) through the Classic inline-edit cells inside the embedded
    ``tabbedLoanAccount`` iframe.
    """

    kind = DeviationObject.CL_CONTRACT.value

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        """Store org base and page timeout."""
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def open(self, tabs: TabProvider, ref: PageRef) -> Page:
        """Open the Lightning record page that embeds the editable form."""
        return await tabs.new_page(ref.url)

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext, log: JobLogger
    ) -> Discovery:
        """Find the single CL contract matching the opportunity product."""
        kind = DeviationObject.CL_CONTRACT.value
        if not context.opportunity_url:
            log("discover: cl_contract: no opportunity link to open")
            return Discovery(
                refs=(unresolved(kind, "Couldn't open the opportunity page"),)
            )
        url = related_list_url(
            absolute_url(context.opportunity_url, self._org_base), _RELATED_LIST
        )
        log(f"discover: cl_contract: opening related list {url}")
        page = await tabs.new_page(url)
        try:
            rows = page.locator("tr.slds-hint-parent")
            count = await settled_row_count(
                rows, related_list_empty(page), self._timeout_ms
            )
            log(f"discover: cl_contract: {count!r} row(s)")
            if count is None:
                return Discovery(
                    refs=(unresolved(kind, "Couldn't open the CL contract list"),)
                )
            contracts = await _contracts(page) if count > 0 else []
        finally:
            await tabs.close_page(page)

        if count > 0 and not contracts:
            log("discover: cl_contract: rows rendered but none were readable")
            return Discovery(
                refs=(unresolved(kind, "Couldn't read the CL contract list"),)
            )

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
            log(
                f"discover: cl_contract: {len(matching)} matching contracts "
                f"for {context.product_type!r} -> {target!r}"
            )
            return Discovery(
                refs=(
                    unresolved(
                        kind,
                        f"There are {len(matching)} CL contracts for this product — "
                        "can't tell which one",
                    ),
                )
            )
        if len(matching) == 1:
            href, cid = matching[0]
            log(f"discover: cl_contract: matched {cid}")
            return Discovery(
                refs=(
                    DiscoveredRef(
                        kind=kind,
                        name=cid,
                        url=absolute_url(href, self._org_base),
                    ),
                )
            )
        log("discover: cl_contract: no contract for the product")
        return Discovery(refs=(absent(kind, "No CL contract for this product"),))

    async def read(
        self, page: Page, targets: Sequence[FieldTarget], log: JobLogger
    ) -> dict[FieldTarget, str | None]:
        """Read the Classic cells for the requested targets."""
        log("read: cl_contract: resolving Classic form frame")
        frame = await _form_frame(page, self._timeout_ms)
        if frame is None:
            log("read: cl_contract: Classic form frame not found")
            return {target: None for target in targets}
        values: dict[FieldTarget, str | None] = {}
        for target in targets:
            name = describe_target(target)
            cell = await self._value_cell(frame, target, self._timeout_ms)
            if cell is None:
                log(f"read: cl_contract: {name}: cell not found")
                values[target] = None
                continue
            values[target] = await safe_inner_text(cell, self._timeout_ms)
            log(f"read: cl_contract: {name}={values[target]!r}")
        return values

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str], log: JobLogger
    ) -> dict[FieldTarget, WriteOutcome]:
        """Inline-edit and save each Classic cell, returning per-target outcomes."""
        log("apply: cl_contract: resolving Classic form frame")
        frame = await _form_frame(page, self._timeout_ms)
        if frame is None:
            log("apply: cl_contract: Classic form frame not found")
            return {target: WriteOutcome.UNKNOWN for target in values}
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        for target, value in values.items():
            name = describe_target(target)
            cell = await self._value_cell(frame, target, self._timeout_ms)
            if cell is None:
                log(f"apply: cl_contract: {name}: cell not found")
                outcomes[target] = WriteOutcome.UNKNOWN
                continue
            outcomes[target] = await self._edit(frame, cell, target, value, log)
        return outcomes

    async def _label_cell(
        self, frame: Frame, target: FieldTarget, timeout_ms: int
    ) -> Locator | None:
        """Find the ``td.labelCol`` for a target, scoping by section if repeated."""
        deadline = Deadline(timeout_ms)
        matches = await _matching_labels(
            frame.locator("td.labelCol"), target.label, deadline.remaining_ms()
        )
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1 and target.section is not None:
            header = frame.get_by_text(target.section, exact=True).first
            try:
                header_count = await bounded(header.count, deadline)
            except TimeoutError:
                return matches[0]
            if header_count > 0:
                table = header.locator("xpath=ancestor::table[1]")
                try:
                    table_count = await bounded(table.count, deadline)
                except TimeoutError:
                    return matches[0]
                if table_count > 0:
                    scoped = await _matching_labels(
                        table.locator("td.labelCol"),
                        target.label,
                        deadline.remaining_ms(),
                    )
                    if scoped:
                        return scoped[0]
        return matches[0] if matches else None

    async def _value_cell(
        self, frame: Frame, target: FieldTarget, timeout_ms: int
    ) -> Locator | None:
        """The value cell immediately following a target's label cell."""
        label = await self._label_cell(frame, target, timeout_ms)
        if label is None:
            return None
        cell = label.locator("xpath=following-sibling::td[1]")
        try:
            count = await bounded(cell.count, Deadline(timeout_ms))
        except TimeoutError:
            return None
        return cell.first if count > 0 else None

    async def _edit(
        self,
        frame: Frame,
        cell: Locator,
        target: FieldTarget,
        value: str,
        log: JobLogger,
    ) -> WriteOutcome:
        """Double-click the cell, fill it, save and verify the read-back."""
        name = describe_target(target)
        try:
            log(f"apply: cl_contract: {name}: double-clicking cell")
            await cell.dblclick(timeout=self._timeout_ms)
            if not await poll(lambda: _has_input(cell), self._timeout_ms):
                log(f"apply: cl_contract: {name}: edit input did not appear")
                return WriteOutcome.UNKNOWN
            log(f"apply: cl_contract: {name}: edit opened")
            log(f"apply: cl_contract: {name}: filling {value!r}")
            actual = await clear_and_fill(
                cell.locator("input").first, value, self._timeout_ms
            )
            if not _same(target, actual, value):
                log(
                    f"apply: cl_contract: {name}: input reads {actual!r}; "
                    f"expected {value!r}"
                )
                return WriteOutcome.UNKNOWN
            log(f"apply: cl_contract: {name}: filled {value!r}")
            save = frame.locator('input[name="inlineEditSave"]')
            log(f"apply: cl_contract: {name}: clicking Save")
            if not await click_first_visible(save, self._timeout_ms):
                log(f"apply: cl_contract: {name}: Save did not become clickable")
                return WriteOutcome.UNKNOWN
            log(f"apply: cl_contract: {name}: save clicked")
            if not await poll(
                lambda: self._saved(frame, target, value), self._timeout_ms
            ):
                log(f"apply: cl_contract: {name}: read-back did not match")
                return WriteOutcome.REJECTED
            log(f"apply: cl_contract: {name}: saved")
            return WriteOutcome.SAVED
        except Exception as exc:  # noqa: BLE001 - Classic AJAX may replace the cell
            logger.debug("cl-contract write failed for %s: %s", target, exc)
            log(f"apply: cl_contract: {name}: error {type(exc).__name__}: {exc}")
            return WriteOutcome.UNKNOWN

    async def _saved(self, frame: Frame, target: FieldTarget, value: str) -> bool:
        """Whether the cell left edit mode and reads back the intended value."""
        cell = await self._value_cell(frame, target, 2000)
        if cell is None or await _has_input(cell):
            return False
        raw = await safe_inner_text(cell, 2000)
        return _same(target, raw, value)


async def _matching_labels(
    labels: Locator, text: str, timeout_ms: int
) -> list[Locator]:
    """All label cells whose trimmed text equals ``text``, within one budget."""
    deadline = Deadline(timeout_ms)
    found: list[Locator] = []
    try:
        count = await bounded(labels.count, deadline)
    except TimeoutError:
        return found
    for index in range(count):
        if deadline.expired:
            break
        cell = labels.nth(index)
        try:
            current = await bounded(
                partial(
                    safe_inner_text,
                    cell,
                    max(1, min(1000, deadline.remaining_ms())),
                ),
                deadline,
            )
        except TimeoutError:
            break
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
