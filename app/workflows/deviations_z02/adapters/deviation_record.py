"""Deviation record page: description, ROI attributes, record ids, Opportunity link."""

from __future__ import annotations

import logging

from playwright.async_api import Locator, Page

from app.salesforce.adapters import (
    AdapterBase,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
)
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02.catalog import DeviationObject
from app.workflows.deviations_z02.description import (
    clean_description,
    parse_description_fields,
)

from .dom import absolute_url, dismiss_banner, safe_inner_text

_HOUSING_ROI_SELECTORS: dict[str, str] = {
    "requested_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Requested_ROI__c",
    "ideal_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Ideal_ROI_Formula__c",
    "updated_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Updated_ROI__c",
    "requested_variance": "sfdc:RecordField.Consumer_Loan_Deviation__c.Requested_Variance__c",
}

_DESCRIPTION_LABEL = "Loan Deviation Description"

logger = logging.getLogger(__name__)


class DeviationRecordAdapter(AdapterBase):
    kind = DeviationObject.DEVIATION.value

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        url = absolute_url(context.record_url, self._org_base)
        page = await tabs.new_page(url)
        try:
            await dismiss_banner(page)
            label = page.get_by_text(_DESCRIPTION_LABEL, exact=True).first
            try:
                await label.wait_for(timeout=self._timeout_ms)
            except Exception:  # noqa: BLE001 - record page did not render
                return Discovery(
                    skip_reason=f"no detail page for {context.item_key}"
                )

            description = await _description(page, label)
            values = await _housing_values(page)
            opportunity = await _opportunity_ref(page, self._org_base)
            attributes: dict[str, str | None] = {
                "description": description,
                "record_id": _record_id(url),
                "record_url": url,
                **values,
            }
            return Discovery(
                refs=(opportunity,) if opportunity is not None else (),
                attributes=attributes,
                fields=parse_description_fields(description),
            )
        finally:
            await tabs.close_page(page)


async def _description(page: Page, label: Locator) -> str:
    """The description body is the widest ancestor text that still contains the label."""
    body: str | None = None
    for depth in (3, 4, 5, 6):
        text = await safe_inner_text(
            label.locator(f"xpath=ancestor-or-self::*[{depth}]"), 2500
        )
        if text and len(text) > len(_DESCRIPTION_LABEL) * 2 and _DESCRIPTION_LABEL in text:
            body = text
            if len(text) > 120:
                break
    return clean_description(body or "")


async def _opportunity_ref(page: Page, org_base: str) -> DiscoveredRef | None:
    for _ in range(10):
        if await page.get_by_role("link").count() >= 3:
            break
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(500)

    links = page.get_by_role("link")
    for index in range(await links.count()):
        locator = links.nth(index)
        href = await locator.get_attribute("href") or ""
        if "/lightning/r/Opportunity/" not in href.split("?")[0]:
            continue
        text = await safe_inner_text(locator, 800)
        return DiscoveredRef(
            kind=DeviationObject.OPPORTUNITY.value,
            name=(text or href)[:80],
            url=absolute_url(href, org_base),
        )
    return None


async def _housing_values(page: Page) -> dict[str, str | None]:
    section = page.get_by_role("button", name="Housing Loan Deviation Details")
    if await section.count() > 0:
        try:
            if await section.first.get_attribute("aria-expanded") != "true":
                await section.first.click(timeout=5000)
                await page.wait_for_timeout(1000)
        except Exception as exc:  # noqa: BLE001 - section may not be collapsible
            logger.debug("housing section toggle failed: %s", exc)

    ideal = (
        '[data-target-selection-name="sfdc:RecordField.'
        'Consumer_Loan_Deviation__c.Ideal_ROI_Formula__c"]'
    )
    for _ in range(10):
        if await page.locator(ideal).count() > 0:
            break
        await page.wait_for_timeout(300)

    return {
        key: await _housing_value(page, selector)
        for key, selector in _HOUSING_ROI_SELECTORS.items()
    }


async def _housing_value(page: Page, selection_name: str) -> str | None:
    locator = page.locator(f'[data-target-selection-name="{selection_name}"]')
    if await locator.count() == 0:
        return None
    first = locator.first
    number = first.locator("lightning-formatted-number")
    if await number.count() > 0:
        text = await safe_inner_text(number.first)
        if text:
            return text
    control = first.locator(".slds-form-element__control")
    if await control.count() > 0:
        text = await safe_inner_text(control.first)
        if text and not text.lower().startswith("edit "):
            return text
    return None


def _record_id(url: str) -> str | None:
    """``…/lightning/r/a2f…/view`` → ``a2f…`` (the last segment is the view mode)."""
    parts = [part for part in url.split("?")[0].rstrip("/").split("/") if part]
    if not parts:
        return None
    if parts[-1] in {"view", "edit", "detail"} and len(parts) > 1:
        return parts[-2]
    return parts[-1]
