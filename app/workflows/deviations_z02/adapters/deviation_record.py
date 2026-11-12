"""Deviation record page: description, ROI attributes, record ids, Opportunity link."""

from __future__ import annotations

import logging

from playwright.async_api import Locator, Page

from app.core.job_logger import JobLogger
from app.salesforce.adapters import (
    AdapterBase,
    DiscoveredRef,
    Discovery,
    DiscoveryContext,
    unresolved,
)
from app.salesforce.tabs import TabProvider
from app.utils.dom import (
    absolute_url,
    click_first_visible,
    dismiss_banner,
    poll,
    safe_inner_text,
)
from app.workflows.deviations_z02.catalog import FIELD_CATALOG, DeviationObject
from app.workflows.deviations_z02.description import (
    clean_description,
    parse_description_changes,
)

#: The custom checkbox that says whether the deviation is implemented.
_IMPLEMENTED_FIELD = 'lightning-input:has([data-name="Implemented__c"])'

#: The action that implements the deviation; no modal follows it.
_IMPLEMENTED_BUTTON = 'button[name="Consumer_Loan_Deviation__c.Implemented"]'

_HOUSING_ROI_SELECTORS: dict[str, str] = {
    "requested_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Requested_ROI__c",
    "ideal_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Ideal_ROI_Formula__c",
    "updated_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Updated_ROI__c",
    "requested_variance": "sfdc:RecordField.Consumer_Loan_Deviation__c.Requested_Variance__c",
}

#: Record-header highlight labels → the read-only attribute keys they populate.
_HIGHLIGHT_ATTRIBUTES: dict[str, str] = {
    "Loan Deviation Type": "loan_deviation_type",
    "Loan Deviation Sub Type": "loan_deviation_sub_type",
}

_DESCRIPTION_LABEL = "Loan Deviation Description"

logger = logging.getLogger(__name__)


class DeviationRecordAdapter(AdapterBase):
    """
    Deviation record: description, ROI values, ids and opportunity link.

    The description is read from the tightest ancestor of its label that still
    contains the whole body; the four ROI fields come from the Housing section,
    which is expanded first. The loan-deviation type and sub-type come from the
    record-header highlights. Only values that changed between the description's Old
    and New blocks are prefilled; unchanged values are stored as ``None`` so the
    operator sees an empty field. Missing values are normal — only a page that never
    renders the description is a skip.
    """

    kind = DeviationObject.DEVIATION.value

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        """Store org base and page timeout."""
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext, log: JobLogger
    ) -> Discovery:
        """Read the record page and everything only it can provide."""
        url = absolute_url(context.record_url, self._org_base)
        log(f"discover: deviation: opening {url}")
        page = await tabs.new_page(url)
        try:
            await dismiss_banner(page)
            label = page.get_by_text(_DESCRIPTION_LABEL, exact=True).first
            try:
                await label.wait_for(timeout=self._timeout_ms)
            except Exception:  # noqa: BLE001 - record page did not render
                log("discover: deviation: record page did not render")
                return Discovery(
                    refs=(
                        unresolved(
                            DeviationObject.OPPORTUNITY.value,
                            "Couldn't open the deviation page",
                        ),
                    )
                )

            log("discover: deviation: reading description")
            description = await _description(page, label)
            log(f"discover: deviation: description {len(description)} char(s)")
            values = await _housing_values(page)
            log(f"discover: deviation: housing values {values}")
            highlights = await _highlight_values(page, self._timeout_ms)
            log(f"discover: deviation: highlights {highlights}")
            opportunity = await _opportunity_ref(page, self._org_base)
            log(
                "discover: deviation: opportunity link "
                f"{opportunity.name if opportunity is not None else 'not found'}"
            )
            attributes: dict[str, str | None] = {
                "description": description,
                "record_id": _record_id(url),
                "record_url": url,
                **values,
                **highlights,
            }
            return Discovery(
                refs=(
                    opportunity
                    if opportunity is not None
                    else unresolved(
                        DeviationObject.OPPORTUNITY.value,
                        "Couldn't find the opportunity link on the deviation page",
                    ),
                ),
                attributes=attributes,
                fields=parse_description_changes(description, FIELD_CATALOG),
            )
        finally:
            await tabs.close_page(page)


    async def open_record(self, tabs: TabProvider, record_url: str) -> Page:
        """
        Open the deviation record page for the final action.

        Called by ``DeviationsZ02Submission`` after validation. ``record_url`` is the
        list row's link (root-relative or absolute) and is resolved against the org base.
        """
        return await tabs.new_page(absolute_url(record_url, self._org_base))

    async def is_implemented(self, page: Page, log: JobLogger) -> bool | None:
        """
        Whether the deviation already shows the Implemented tick.

        ``None`` means the checkbox never rendered, so the pipeline must not guess.
        Called immediately before the final click; the value is also the caller's
        idempotency check after a crash. The record page renders the field twice
        (highlights and detail); any ticked copy means implemented.
        """
        log("execute: deviation: looking for the Implemented checkbox")
        fields = await self._implemented_fields(page)
        if fields is None:
            log("execute: deviation: Implemented checkbox did not render")
            return None
        implemented = await _any_checked(fields)
        log(f"execute: deviation: Implemented tick {'present' if implemented else 'absent'}")
        return implemented

    async def implement(self, page: Page, log: JobLogger) -> bool:
        """
        Click **Implemented** and confirm the checkbox turns ticked.

        Called once per submission, after ``is_implemented`` returned ``False``. Returns
        ``False`` when the button is missing or no copy of the tick is observed within
        the request timeout, so the caller parks the item for review. Playwright errors
        surface to the pipeline as a failed job.
        """
        fields = await self._implemented_fields(page)
        if fields is None:
            log("execute: deviation: Implemented checkbox did not render")
            return False
        if await _any_checked(fields):
            log("execute: deviation: already ticked; no click needed")
            return True
        button = page.locator(_IMPLEMENTED_BUTTON)
        if await button.count() == 0:
            button = page.get_by_role("button", name="Implemented", exact=True)
        log("execute: deviation: clicking Implemented")
        if not await click_first_visible(button, self._timeout_ms):
            log("execute: deviation: Implemented button did not become clickable")
            return False
        confirmed = await poll(lambda: _any_checked(fields), self._timeout_ms)
        log(
            "execute: deviation: tick confirmed"
            if confirmed
            else "execute: deviation: tick did not appear after the click"
        )
        return confirmed

    async def _implemented_fields(self, page: Page) -> Locator | None:
        """Every rendered copy of the Implemented checkbox, once it appears."""
        fields = page.locator(_IMPLEMENTED_FIELD)
        if not await poll(lambda: _has(fields, 1), self._timeout_ms):
            return None
        return fields


async def _has(locator: Locator, minimum: int) -> bool:
    """Whether the locator currently matches at least ``minimum`` elements."""
    return await locator.count() >= minimum


def implemented_from_signals(
    checked_attribute: str | None, check_icons: int, true_titles: int
) -> bool:
    """
    Decide “implemented” from the three signals LWC renders.

    Checked: ``checked`` on the input, or a ``utility:check`` icon, or an icon titled
    ``True``. Unchecked: no attribute and a ``utility:steps`` icon titled ``False``.
    Pure so the detection is unit-tested without a browser.
    """
    return checked_attribute is not None or check_icons > 0 or true_titles > 0


async def _checked(field: Locator) -> bool:
    """Read the readonly checkbox as LWC renders it, using the pure decision."""
    return implemented_from_signals(
        await field.get_attribute("checked"),
        await field.locator('lightning-icon[icon-name="utility:check"]').count(),
        await field.locator('lightning-icon[title="True"]').count(),
    )


async def _any_checked(fields: Locator) -> bool:
    """Whether any rendered copy of the checkbox is ticked."""
    for index in range(await fields.count()):
        if await _checked(fields.nth(index)):
            return True
    return False


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
    """Find the Opportunity link rendered on the record page."""
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
    """Read the four ROI fields from the Housing section."""
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


async def _highlight_values(
    page: Page, timeout_ms: int
) -> dict[str, str | None]:
    """
    Read the loan-deviation type and sub-type from the record header highlights.

    The header renders one ``records-highlights-details-item`` per field; each has a
    ``p.slds-text-title`` label and a ``p.fieldComponent`` value. The values are
    read-only attributes, not editable fields. A missing header yields ``None`` values
    rather than failing the extraction.
    """
    values: dict[str, str | None] = {
        key: None for key in _HIGHLIGHT_ATTRIBUTES.values()
    }
    items = page.locator("records-highlights-details-item")
    if not await poll(lambda: _has(items, 1), min(timeout_ms, 5000)):
        return values
    count = await items.count()
    for index in range(count):
        item = items.nth(index)
        title = await safe_inner_text(item.locator("p.slds-text-title").first, 1000)
        key = _HIGHLIGHT_ATTRIBUTES.get(title or "")
        if key is None:
            continue
        value = item.locator("p.fieldComponent").first
        if await value.count() > 0:
            values[key] = await safe_inner_text(value, 2000)
    return values


async def _housing_value(page: Page, selection_name: str) -> str | None:
    """Read one labelled field, or ``None``."""
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
