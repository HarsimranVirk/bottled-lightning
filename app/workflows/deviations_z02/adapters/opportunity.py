"""Opportunity page: product type (extraction) and the editable values.

The editable values live in custom ``field-section2`` accordions. The sections load
lazily, so every read/write scrolls the section into view and waits for the field to
render before touching it. Inline editing is the pencil button on the field followed by
the page-level Save button; the value is read back from ``.test-id__field-value``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from playwright.async_api import Locator, Page

from app.core.field import FieldTarget, ValueType, normalise
from app.core.status import WriteOutcome
from app.salesforce.adapters import AdapterBase, Discovery, DiscoveryContext
from app.salesforce.tabs import TabProvider
from app.utils.dom import (
    absolute_url,
    clear_and_fill,
    click_first_visible,
    poll,
    safe_body_text,
    safe_inner_text,
    wait_for_text,
)
from app.workflows.deviations_z02.catalog import DeviationObject

logger = logging.getLogger(__name__)

#: The stable field ids inside each section (confirmed against the live org).
_FIELD_IDS: Mapping[str, str] = {
    "Property Value Ex. Reg & ST(Financeable)": (
        "RecordProperty_Value_Financeable_cField"
    ),
    "Loan Amount": "RecordLoan_Amount_cField",
    "Tenure (Yrs)": "RecordTenure_cField",
    "EMIs & other fixed pmts inc HFFC Loan": (
        "RecordEMIs_and_other_fixed_payments_including_cField"
    ),
    "ROI": "RecordROI_cField",
}

_TENURE_LABEL = "Tenure (Yrs)"
_ROI_LABEL = "ROI"


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


async def _has_input(field: Locator) -> bool:
    """Whether the field is currently in inline-edit mode."""
    return await field.locator("input").count() > 0


async def _has_value(field: Locator) -> bool:
    """Whether the field has rendered its read-only value (lazy section loaded)."""
    return await field.locator(".test-id__field-value").count() > 0


async def _has_text(value: Locator) -> bool:
    """Whether a value element exists and has non-empty text."""
    if await value.count() == 0:
        return False
    return await safe_inner_text(value, 1000) is not None


async def _has_count(locator: Locator, minimum: int) -> bool:
    """Whether a locator currently matches at least ``minimum`` elements."""
    return await locator.count() >= minimum


def _value_type(target: FieldTarget) -> ValueType:
    """The storage type of a target on this page."""
    if target.label == _TENURE_LABEL:
        return ValueType.TENURE_MONTHS
    if target.label == _ROI_LABEL:
        return ValueType.NUMBER
    return ValueType.AMOUNT


def _same(target: FieldTarget, raw: str | None, intended: str) -> bool:
    """Whether a displayed value canonicalises to the intended value."""
    if raw is None:
        return False
    canonical = _canonical(target, raw)
    if canonical is None:
        return False
    value_type = _value_type(target)
    try:
        return normalise(canonical, value_type) == normalise(intended, value_type)
    except ValueError:
        return canonical.strip() == intended.strip()


def _canonical(target: FieldTarget, raw: str | None) -> str | None:
    """Convert the page's display unit into the field's canonical unit."""
    if raw is None:
        return None
    if target.label != _TENURE_LABEL:
        return raw
    try:
        years = Decimal(raw.strip())
    except InvalidOperation:
        return raw
    return str(int((years * 12).to_integral_value()))


def _display(target: FieldTarget, value: str) -> str:
    """Convert the canonical value into what the page input expects."""
    if target.label != _TENURE_LABEL:
        return value
    try:
        months = Decimal(value)
    except InvalidOperation:
        return value
    years = (months / Decimal(12)).quantize(Decimal("0.01"))
    return format(years.normalize(), "f")


class OpportunityAdapter(AdapterBase):
    """
    Opportunity page: product type and the editable loan parameters.

    Extraction reads the product type from the body. Submission edits the catalogue
    targets in their sections: property value, loan amount, ROI, tenure (shown in years)
    and the HFFC-inclusive EMI.
    """

    kind = DeviationObject.OPPORTUNITY.value

    def __init__(self, org_base: str, timeout_ms: int) -> None:
        """Store org base and page timeout."""
        self._org_base = org_base
        self._timeout_ms = timeout_ms

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        """Read the product type shown on the opportunity."""
        if not context.opportunity_url:
            return Discovery()
        page = await tabs.new_page(absolute_url(context.opportunity_url, self._org_base))
        try:
            await wait_for_text(page, "Product Type", self._timeout_ms)
            body = await safe_body_text(page)
            return Discovery(
                attributes={"product_type": product_type_from(body or "")}
            )
        finally:
            await tabs.close_page(page)

    async def read(
        self, page: Page, targets: Sequence[FieldTarget]
    ) -> dict[FieldTarget, str | None]:
        """Read the target values, converting the tenure display to months."""
        values: dict[FieldTarget, str | None] = {}
        for target in targets:
            field = await self._field(page, target)
            if field is None:
                values[target] = None
                continue
            values[target] = _canonical(target, await self._read_text(field))
        return values

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str]
    ) -> dict[FieldTarget, WriteOutcome]:
        """Edit each target inline and save it, returning per-target outcomes."""
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        for target, value in values.items():
            field = await self._field(page, target)
            if field is None:
                outcomes[target] = WriteOutcome.UNKNOWN
                continue
            outcomes[target] = await self._edit(page, field, target, value)
        return outcomes

    async def _section(self, page: Page, target: FieldTarget) -> Locator | None:
        """Locate the accordion named by the target, if it declares one."""
        if target.section is None:
            return None
        section = page.locator("div.field-section2").filter(has_text=target.section).first
        if not await poll(lambda: _has_count(section, 1), self._timeout_ms):
            return None
        return section

    async def _field(self, page: Page, target: FieldTarget) -> Locator | None:
        """Find one target's field and wait for its lazy section to render."""
        section = await self._section(page, target)
        scope = section if section is not None else page
        field_id = _FIELD_IDS.get(target.label)
        field = (
            scope.locator(f'flexipage-field[data-field-id="{field_id}"]')
            if field_id is not None
            else scope.locator("flexipage-field").filter(has_text=target.label)
        )
        if section is not None:
            try:
                await section.scroll_into_view_if_needed(timeout=self._timeout_ms)
            except Exception as exc:  # noqa: BLE001 - section may be re-rendering
                logger.debug("section scroll failed: %s", exc)
        ready = await poll(lambda: _has_value(field), self._timeout_ms)
        if not ready:
            return None
        return field.first

    async def _read_text(self, field: Locator) -> str | None:
        """Wait for the field's value text to populate, then return it."""
        value = field.locator(".test-id__field-value").first
        await poll(lambda: _has_text(value), min(self._timeout_ms, 15_000))
        return await safe_inner_text(value, 2000)

    async def _edit(
        self, page: Page, field: Locator, target: FieldTarget, value: str
    ) -> WriteOutcome:
        """Open one inline edit, fill it, save and verify the read-back."""
        try:
            edit = field.get_by_role("button", name="Edit", exact=False)
            if await edit.count() == 0:
                return WriteOutcome.UNKNOWN
            await edit.first.click(timeout=self._timeout_ms)
            if not await poll(lambda: _has_input(field), self._timeout_ms):
                return WriteOutcome.UNKNOWN
            actual = await clear_and_fill(
                field.locator("input").first, _display(target, value)
            )
            if not _same(target, actual, value):
                return WriteOutcome.UNKNOWN
            save = page.get_by_role("button", name="Save", exact=True)
            if not await click_first_visible(save, self._timeout_ms):
                return WriteOutcome.UNKNOWN
            if not await poll(
                lambda: self._saved(field, target, value), self._timeout_ms
            ):
                return WriteOutcome.REJECTED
            return WriteOutcome.SAVED
        except Exception as exc:  # noqa: BLE001 - page may die mid-save
            logger.debug("opportunity write failed for %s: %s", target, exc)
            return WriteOutcome.UNKNOWN

    async def _saved(self, field: Locator, target: FieldTarget, value: str) -> bool:
        """Whether the field left edit mode and reads back the intended value."""
        if await _has_input(field):
            return False
        raw = await self._read_text(field)
        return _same(target, raw, value)
