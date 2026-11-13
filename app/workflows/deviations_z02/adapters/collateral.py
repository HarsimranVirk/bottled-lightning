"""Collateral discovery and the editable Property Value on the Details tab.

The collateral record is a standard Lightning record page. Its Property Value field is
edited by double-clicking the value (the standard record-field inline edit), filling the
input, and pressing the page-level Save button.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from playwright.async_api import Locator, Page

from app.core.field import FieldTarget, ValueType, normalise
from app.core.job_logger import JobLogger
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
    absolute_url,
    clear_and_fill,
    click_first_visible,
    poll,
    related_list_empty,
    related_list_url,
    safe_inner_text,
    settled_row_count,
)
from app.workflows.deviations_z02.catalog import DeviationObject

logger = logging.getLogger(__name__)

_RELATED_LIST = "Collateral__r"


async def _has_value(item: Locator) -> bool:
    """Whether the record field has rendered its read-only value."""
    return await item.locator(".test-id__field-value").count() > 0


async def _has_input(item: Locator) -> bool:
    """Whether the record field is in inline-edit mode."""
    return await item.locator("input").count() > 0


def _same(raw: str | None, intended: str) -> bool:
    """Whether a displayed amount canonicalises to the intended amount."""
    if raw is None:
        return False
    try:
        return normalise(raw, ValueType.AMOUNT) == normalise(intended, ValueType.AMOUNT)
    except ValueError:
        return raw.strip() == intended.strip()


class CollateralAdapter(AdapterBase):
    """
    Collateral link for the opportunity and its editable Property Value.

    More than one collateral on the opportunity is ambiguous (the deviation would
    have to guess which), so it skips; exactly one is recorded as a ref. Submission
    edits the Property Value on the Details tab.
    """

    kind = DeviationObject.COLLATERAL.value

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext, log: JobLogger
    ) -> Discovery:
        """Find the single collateral attached to the opportunity."""
        kind = DeviationObject.COLLATERAL.value
        if not context.opportunity_url:
            log("discover: collateral: no opportunity link to open")
            return Discovery(refs=(unresolved(kind, "Couldn't open the opportunity page"),))
        url = related_list_url(
            absolute_url(context.opportunity_url, self._org_base), _RELATED_LIST
        )
        log(f"discover: collateral: opening related list {url}")
        page = await tabs.new_page(url)
        try:
            rows = page.locator("tr.slds-hint-parent")
            count = await settled_row_count(rows, related_list_empty(page), self._timeout_ms)
            log(f"discover: collateral: {count!r} row(s)")
            if count is None:
                return Discovery(refs=(unresolved(kind, "Couldn't open the collateral list"),))
            if count > 1:
                return Discovery(
                    refs=(
                        unresolved(
                            kind,
                            f"There are {count} collateral records — "
                            "can't tell which one",
                        ),
                    )
                )
            if count == 1:
                ref = await _first_collateral(rows.nth(0), self._org_base)
                if ref is not None:
                    log(f"discover: collateral: matched {ref.name}")
                    return Discovery(refs=(ref,))
                return Discovery(
                    refs=(unresolved(kind, "Couldn't open the collateral record"),)
                )
            log("discover: collateral: related list is empty")
            return Discovery(
                refs=(absent(kind, "No collateral attached to this opportunity"),)
            )
        finally:
            await tabs.close_page(page)

    async def read(
        self, page: Page, targets: Sequence[FieldTarget], log: JobLogger
    ) -> dict[FieldTarget, str | None]:
        """Read the Property Value (the only editable collateral target)."""
        values: dict[FieldTarget, str | None] = {}
        for target in targets:
            name = describe_target(target)
            log(f"read: collateral: {name}: locating field")
            item = await self._item(page, target)
            if item is None:
                log(f"read: collateral: {name}: field did not render")
                values[target] = None
                continue
            values[target] = await safe_inner_text(
                item.locator(".test-id__field-value").first, self._timeout_ms
            )
            log(f"read: collateral: {name}={values[target]!r}")
        return values

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str], log: JobLogger
    ) -> dict[FieldTarget, WriteOutcome]:
        """Inline-edit and save each target, returning per-target outcomes."""
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        for target, value in values.items():
            name = describe_target(target)
            log(f"apply: collateral: {name}: locating field")
            item = await self._item(page, target)
            if item is None:
                log(f"apply: collateral: {name}: field did not render")
                outcomes[target] = WriteOutcome.UNKNOWN
                continue
            outcomes[target] = await self._edit(page, item, target, value, log)
        return outcomes

    async def _item(self, page: Page, target: FieldTarget) -> Locator | None:
        """Find the record field, switching to the Details tab if needed."""
        selector = f'records-record-layout-item[field-label="{target.label}"]'
        item = page.locator(selector).first
        if await item.count() == 0 and target.section is not None:
            tab = page.get_by_role("tab", name=target.section, exact=True)
            if await tab.count() > 0:
                try:
                    await tab.first.click(timeout=self._timeout_ms)
                except Exception as exc:  # noqa: BLE001 - tab may already be active
                    logger.debug("collateral tab click failed: %s", exc)
        ready = await poll(lambda: _has_value(item), self._timeout_ms)
        return item if ready else None

    async def _edit(
        self,
        page: Page,
        item: Locator,
        target: FieldTarget,
        value: str,
        log: JobLogger,
    ) -> WriteOutcome:
        """Double-click the value, fill it, save and verify the read-back."""
        name = describe_target(target)
        try:
            log(f"apply: collateral: {name}: double-clicking value")
            await item.locator(".test-id__field-value").first.dblclick(
                timeout=self._timeout_ms
            )
            log(f"apply: collateral: {name}: edit opened")
            if not await poll(lambda: _has_input(item), self._timeout_ms):
                log(f"apply: collateral: {name}: edit input did not appear")
                return WriteOutcome.UNKNOWN
            log(f"apply: collateral: {name}: filling {value!r}")
            actual = await clear_and_fill(
                item.locator("input").first, value, self._timeout_ms
            )
            if not _same(actual, value):
                log(
                    f"apply: collateral: {name}: input reads {actual!r}; "
                    f"expected {value!r}"
                )
                return WriteOutcome.UNKNOWN
            log(f"apply: collateral: {name}: filled {value!r}")
            save = page.get_by_role("button", name="Save", exact=True)
            log(f"apply: collateral: {name}: clicking Save")
            if not await click_first_visible(save, self._timeout_ms):
                log(f"apply: collateral: {name}: Save did not become clickable")
                return WriteOutcome.UNKNOWN
            log(f"apply: collateral: {name}: save clicked")
            if not await poll(lambda: self._saved(item, value), self._timeout_ms):
                log(f"apply: collateral: {name}: read-back did not match")
                return WriteOutcome.REJECTED
            log(f"apply: collateral: {name}: saved")
            return WriteOutcome.SAVED
        except Exception as exc:  # noqa: BLE001 - page may die mid-save
            logger.debug("collateral write failed for %s: %s", target, exc)
            log(f"apply: collateral: {name}: error {type(exc).__name__}: {exc}")
            return WriteOutcome.UNKNOWN

    async def _saved(self, item: Locator, value: str) -> bool:
        """Whether the field left edit mode and reads back the intended amount."""
        if await _has_input(item):
            return False
        raw = await safe_inner_text(
            item.locator(".test-id__field-value").first, 2000
        )
        return _same(raw, value)


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
