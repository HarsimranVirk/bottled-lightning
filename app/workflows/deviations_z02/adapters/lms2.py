"""LMS 2.0 CL contract and collateral: discovery and editable values.

Both objects live behind a Lightning tab (``flexipage_tab2``) whose related list is a
custom component rendered in a shadow root, so extraction reads rows with one small JS
helper. A loan legitimately has several LMS 2.0 CL contracts, so the CL-contract variant
is narrowed by the same product mapping as the regular CL-contract related list; only two
rows matching the *target* product are ambiguous.

Submission edits the custom detail pages: the collateral page's Edit form (Financials →
Property Value) and the CL contract page's LOAN QUICK ACTIONS → Contract Modification
form (Loan amount / Tenure cards). The contract page must be approved before it accepts a
modification, so the adapter reads the page's approval bar and approves a pending contract
first (FR-6.17). Both pages are LWC shadow DOM, so all locators go through Playwright's
shadow-piercing engine and never through ``page.evaluate``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import partial

from playwright.async_api import Dialog, Locator, Page

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
    Deadline,
    absolute_url,
    bounded,
    clear_and_fill,
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
_APPROVAL_STATUS = "span.pill-status"
_APPROVE_BUTTON = "button.approval-btn-approve"
_APPROVE_CONFIRM_BUTTON = "button.btn-approval-approve"
_CONTRACT_HOST = "c-cl-contract-detail"
_DIALOG_SELECTORS = (
    "div.modal-box",
    "div.modal-backdrop",
    "div.slds-modal",
    "section.slds-modal",
    "section[role='dialog']",
    "div[role='dialog']",
    "lightning-dialog",
)
_CONFIRM_BUTTON_NAMES = ("Confirm", "Approve", "Yes", "OK")
_APPROVED_MARKER = "approved"
_REJECTED_MARKER = "rejected"
_PENDING_MARKER = "pending approval"
#: How long to wait for the custom contract header to render after navigation.
#:
#: ``TabGroup.new_page`` returns at ``domcontentloaded``; the ``c-cl-contract-detail``
#: LWC and its shadow root appear a few seconds later. 20 s covers a slow org without
#: making a genuinely unsupported page look like a hung job.
_APPROVAL_READY_MS = 20_000


class ApprovalAction(StrEnum):
    """What the LMS 2.0 contract header says a write must do first (FR-6.17)."""

    PROCEED = "proceed"
    APPROVE = "approve"
    REFUSE = "refuse"


@dataclass(frozen=True, slots=True)
class LmsRow:
    """One row of an LMS 2.0 related list."""

    data_id: str
    """Stable row identifier from the LMS 2.0 table, used to re-open the record."""

    name: str
    """First cell's text, i.e. the contract/collateral id shown in the list."""

    cells: tuple[str, ...]
    """All cell texts in column order, used for exact product matching."""


def match_rows(rows: Sequence[LmsRow], target: str | None) -> list[LmsRow]:
    """Rows whose cell text equals the target product.

    With no target every row is a candidate, which keeps the old "cannot disambiguate"
    behaviour when the opportunity product is unknown. Exact cell equality avoids
    matching ``Home Loan Resale`` when the target is ``Home Loan``.
    """
    if target is None:
        return list(rows)
    return [row for row in rows if target in row.cells]


def approval_status(texts: Sequence[str]) -> str | None:
    """
    Pick the approval-state pill out of the contract header's status pills.

    The LMS 2.0 contract header renders several ``span.pill-status`` values (for example
    ``Pending Disbursal``, the system date and ``Pending Approval``). Only the text that
    starts with an approval state is returned, with its original spelling preserved for
    logs. Pending wins over rejected, which wins over approved, so an unrelated
    "Approved" pill can never hide a pending contract. Case-insensitive; ``None`` when no
    pill names an approval state.

    Example:
        approval_status(["Pending Disbursal", "Pending Approval"]) -> "Pending Approval"
    """
    matched = [
        text.strip()
        for text in texts
        if _approval_state_prefix(_normalise_status(text)) is not None
    ]
    if not matched:
        return None
    for marker in (_PENDING_MARKER, _REJECTED_MARKER):
        for text in matched:
            if _normalise_status(text).startswith(marker):
                return text
    return matched[0]


def _normalise_status(text: str) -> str:
    """Lower-case a pill and drop leading icons/punctuation before matching."""
    return re.sub(r"^[^a-z]+", "", text.strip().lower())


def _approval_state_prefix(lowered: str) -> str | None:
    """The approval-state prefix in a pill's text, or ``None`` for unrelated pills."""
    for marker in (_PENDING_MARKER, _REJECTED_MARKER, _APPROVED_MARKER):
        if lowered.startswith(marker):
            return marker
    return None


def approval_action(status_text: str | None, can_approve: bool) -> ApprovalAction:
    """
    Decide what the approval gate must do before Contract Modification.

    ``can_approve`` is whether the page currently shows a visible Approve control. A
    readable approved state proceeds; a rejected state refuses; a pending or unreadable
    state is approved only when the control exists. Every other combination refuses
    rather than writing to a contract whose state is unknown (FR-6.17, D-02/D-04).
    """
    lowered = _normalise_status(status_text or "")
    if lowered.startswith(_APPROVED_MARKER):
        return ApprovalAction.PROCEED
    if lowered.startswith(_REJECTED_MARKER):
        return ApprovalAction.REFUSE
    if lowered.startswith(_PENDING_MARKER):
        return ApprovalAction.APPROVE if can_approve else ApprovalAction.REFUSE
    if can_approve:
        return ApprovalAction.APPROVE
    return ApprovalAction.REFUSE


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


def _same_value(target: FieldTarget, raw: str | None, intended: str) -> bool:
    """Whether a Contract Modification input equals the intended value."""
    if raw is None:
        return False
    value_type = (
        ValueType.TENURE_MONTHS if target.section == "Tenure" else ValueType.AMOUNT
    )
    try:
        return normalise(raw, value_type) == normalise(intended, value_type)
    except ValueError:
        return raw.strip() == intended.strip()


class _Lms2Adapter(AdapterBase):
    """Shared discovery for the two LMS 2.0 related lists."""

    host_tag: str = ""
    """Custom element wrapping the list, e.g. ``c-lms2-cl-contract``; the adapter reads
    rows out of its shadow root."""

    detail_path: str = ""
    """Path fragment that opens one record's LMS 2.0 page, e.g. ``/s/lms2/…``."""

    uuid_param: str = ""
    """Query parameter carrying the record uuid on ``detail_path``."""

    object_kind: str = ""
    """Declared object kind this subclass serves, e.g. ``lms2_cl_contract``."""

    matches_product: bool = False
    """Whether the related list must be matched to the opportunity's product before a row
    is chosen."""

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext, log: JobLogger
    ) -> Discovery:
        """Open the LMS tab on the opportunity and pick the matching row."""
        label = self.object_kind.replace("_", " ")
        if not context.opportunity_url:
            log(f"discover: {self.object_kind}: no opportunity link to open")
            return Discovery(
                refs=(unresolved(self.object_kind, "Couldn't open the opportunity page"),)
            )
        page = await tabs.new_page(
            absolute_url(context.opportunity_url, self._org_base)
        )
        try:
            log(f"discover: {self.object_kind}: opening LMS tab")
            await _open_lms_tab(page, self._timeout_ms)
            rows = await _await_lms_rows(page, self.host_tag, self._timeout_ms)
            log(
                "discover: "
                f"{self.object_kind}: "
                f"{'did not render' if rows is None else f'{len(rows)} row(s)'}"
            )
        finally:
            await tabs.close_page(page)

        if rows is None:
            return Discovery(
                refs=(
                    unresolved(
                        self.object_kind,
                        f"Couldn't open the LMS 2.0 {label} list",
                    ),
                )
            )

        target = None
        if self.matches_product and context.product_type:
            target = CL_CONTRACT_PRODUCT_MAP.get(context.product_type)
        candidates = match_rows(rows, target) if self.matches_product else list(rows)

        if len(candidates) > 1:
            detail = (
                f" for {context.product_type} -> {target}" if target is not None else ""
            )
            log(f"discover: {self.object_kind}: {len(candidates)} matching rows{detail}")
            return Discovery(
                refs=(
                    unresolved(
                        self.object_kind,
                        f"There are {len(candidates)} LMS 2.0 {label} records — "
                        "can't tell which one",
                    ),
                )
            )
        if len(candidates) == 1:
            row = candidates[0]
            if row.data_id:
                url = (
                    f"{self._org_base}/lightning/n/{self.detail_path}"
                    f"?c__{self.uuid_param}={row.data_id}"
                )
                log(f"discover: {self.object_kind}: matched {row.name or row.data_id}")
                return Discovery(
                    refs=(
                        DiscoveredRef(
                            kind=self.object_kind,
                            name=row.name or row.data_id,
                            url=url,
                        ),
                    )
                )
            log(f"discover: {self.object_kind}: matched row has no id")
            return Discovery(
                refs=(
                    unresolved(
                        self.object_kind,
                        f"Couldn't open the LMS 2.0 {label} record",
                    ),
                )
            )
        log(f"discover: {self.object_kind}: no matching row")
        return Discovery(
            refs=(absent(self.object_kind, f"No LMS 2.0 {label} for this item"),)
        )


class Lms2ClContractAdapter(_Lms2Adapter):
    """LMS 2.0 CL contract: editable through Contract Modification."""

    kind = DeviationObject.LMS2_CL_CONTRACT.value
    object_kind = DeviationObject.LMS2_CL_CONTRACT.value
    host_tag = "c-lms-cl-contract-related-list"
    detail_path = "CL_Contract_Detail"
    uuid_param = "loanId"
    matches_product = True

    async def read(
        self, page: Page, targets: Sequence[FieldTarget], log: JobLogger
    ) -> dict[FieldTarget, str | None]:
        """Read the Contract Modification form's CURRENT values."""
        values: dict[FieldTarget, str | None] = {}
        try:
            log("read: lms2_cl_contract: opening Contract Modification")
            if not await self._open_modification(page, log):
                log("read: lms2_cl_contract: Contract Modification did not open")
                return {target: None for target in targets}
            for target in targets:
                name = describe_target(target)
                log(f"read: lms2_cl_contract: {name}: locating card")
                card = await self._card(page, target)
                if card is None:
                    log(f"read: lms2_cl_contract: {name}: card did not render")
                    values[target] = None
                    continue
                raw = await safe_inner_text(
                    card.locator(".mod-current-value").first, self._timeout_ms
                )
                values[target] = (
                    _tenure_months(raw) if target.section == "Tenure" else raw
                )
                log(f"read: lms2_cl_contract: {name}={values[target]!r}")
        finally:
            await self._cancel_modification(page)
        return values

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str], log: JobLogger
    ) -> dict[FieldTarget, WriteOutcome]:
        """Approve the contract when pending, then fill the cards and Save Changes."""
        log("apply: lms2_cl_contract: checking approval")
        if not await self.ensure_approved(page, log):
            return {target: WriteOutcome.UNKNOWN for target in values}
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        log("apply: lms2_cl_contract: opening Contract Modification")
        if not await self._open_modification(page, log):
            log("apply: lms2_cl_contract: Contract Modification did not open")
            return {target: WriteOutcome.UNKNOWN for target in values}
        try:
            for target, value in values.items():
                name = describe_target(target)
                log(f"apply: lms2_cl_contract: {name}: locating card")
                card = await self._card(page, target)
                if card is None:
                    log(f"apply: lms2_cl_contract: {name}: card did not render")
                    outcomes[target] = WriteOutcome.UNKNOWN
                    continue
                log(f"apply: lms2_cl_contract: {name}: filling {value!r}")
                actual = await clear_and_fill(
                    card.locator("input").first, value, self._timeout_ms
                )
                if not _same_value(target, actual, value):
                    log(
                        f"apply: lms2_cl_contract: {name}: input reads {actual!r}; "
                        f"expected {value!r}"
                    )
                    return {
                        pending: WriteOutcome.UNKNOWN for pending in values
                    }
                log(f"apply: lms2_cl_contract: {name}: filled {value!r}")
                outcomes[target] = WriteOutcome.SAVED
            save = page.get_by_role("button", name="Save Changes", exact=True)
            log("apply: lms2_cl_contract: clicking Save Changes")
            if not await click_first_visible(save, self._timeout_ms):
                log("apply: lms2_cl_contract: Save Changes did not become clickable")
                return {target: WriteOutcome.UNKNOWN for target in values}
            log("apply: lms2_cl_contract: Save Changes clicked")
            closed = await poll(
                lambda: self._form_closed(page), self._timeout_ms
            )
            if not closed:
                log("apply: lms2_cl_contract: form still open after save")
                return {target: WriteOutcome.REJECTED for target in values}
            log("apply: lms2_cl_contract: form closed")
            return outcomes
        except Exception as exc:  # noqa: BLE001 - page may re-render mid-save
            logger.debug("lms cl-contract write failed: %s", exc)
            log(f"apply: lms2_cl_contract: error {type(exc).__name__}: {exc}")
            return {target: WriteOutcome.UNKNOWN for target in values}
        finally:
            await self._cancel_modification(page)

    async def ensure_approved(self, page: Page, log: JobLogger) -> bool:
        """
        Public approval seam for workflows that only approve the contract.

        ``deviations_z02`` calls this from ``write()`` before Contract Modification;
        the separate ``lms2_approval`` workflow calls it directly with the contract page
        already open. Delegating here keeps one implementation of the approval bar,
        modal confirmation and post-click polling. Returns ``True`` when the page is
        approved, including when it was already approved before the call.
        """
        return await self._ensure_approved(page, log)

    async def _ensure_approved(self, page: Page, log: JobLogger) -> bool:
        """
        Make sure the LMS 2.0 contract accepts a Contract Modification.

        Called by ``write()`` before the modification form is opened. An approved
        contract returns ``True`` without a click; a pending one is approved and its new
        state polled up to the request timeout. A rejected, unreadable or unconfirmed
        contract returns ``False`` so the caller writes nothing (FR-6.17). The approval
        is a one-way SF side effect and is never rolled back (D-05).

        The custom header renders after ``domcontentloaded``, so this waits for its
        approval bar before reading the state; without that wait a pending contract
        looks unreadable and is refused on the first job after navigation.
        """
        log("apply: lms2_cl_contract: waiting for approval bar")
        await self._await_approval_bar(page, log)
        status, can_approve = await self._approval_state(page)
        action = approval_action(status, can_approve)
        log(f"apply: lms2_cl_contract: approval status={status!r} action={action.value}")
        if action is ApprovalAction.PROCEED:
            return True
        if action is not ApprovalAction.APPROVE:
            logger.warning(
                "lms cl-contract approval refused (status=%r, approve=%s)",
                status,
                can_approve,
            )
            log("apply: lms2_cl_contract: approval refused; writing nothing")
            return False
        logger.info("lms cl-contract is pending approval; approving before write")
        log("apply: lms2_cl_contract: approving pending contract")
        if not await self._click_approve(page, log):
            logger.warning("lms cl-contract approve control could not be clicked")
            log("apply: lms2_cl_contract: approve control could not be clicked")
            return False
        approved = await poll(lambda: self._is_approved(page), self._timeout_ms)
        if not approved:
            logger.warning(
                "lms cl-contract approval was not confirmed (was %r)", status
            )
            log("apply: lms2_cl_contract: approval was not confirmed")
        else:
            log("apply: lms2_cl_contract: approval confirmed")
        return approved

    async def _await_approval_bar(self, page: Page, log: JobLogger) -> None:
        """
        Wait for the custom contract header and its approval signal to render.

        Called at the start of ``ensure_approved``. The Lightning page reaches
        ``domcontentloaded`` before the ``c-cl-contract-detail`` LWC mounts, so an
        immediate read returns no pill and no Approve control. This polls for the host
        first, then for a readable approval pill or the Approve button, bounded by
        ``_APPROVAL_READY_MS``. A page that never renders a signal returns after the
        wait and the normal gate refuses it as before.
        """
        host = page.locator(_CONTRACT_HOST)
        if not await poll(lambda: _is_visible(host), _APPROVAL_READY_MS):
            log("apply: lms2_cl_contract: contract header did not render")
            return
        if not await poll(
            lambda: self._has_approval_signal(page), _APPROVAL_READY_MS
        ):
            log("apply: lms2_cl_contract: approval bar did not render")

    async def _has_approval_signal(self, page: Page) -> bool:
        """Whether the page currently exposes an approval pill or Approve control."""
        status, can_approve = await self._approval_state(page)
        return status is not None or can_approve

    async def _approval_state(self, page: Page) -> tuple[str | None, bool]:
        """
        Read the contract header's approval pill and Approve control.

        Returns the matching pill text (or ``None``) and whether the Approve button is
        visible. Both live in the ``c-cl-contract-detail`` shadow root, which Playwright
        locators pierce. Read-only; a re-render mid-read degrades to "unknown" rather
        than raising.
        """
        scope = await _contract_scope(page)
        pills = scope.locator(_APPROVAL_STATUS)
        texts: list[str] = []
        try:
            count = await pills.count()
            for index in range(count):
                text = await safe_inner_text(pills.nth(index), 2000)
                if text is not None:
                    texts.append(text)
        except Exception as exc:  # noqa: BLE001 - page may re-render mid-read
            logger.debug("lms approval status read failed: %s", exc)
        can_approve = await _is_visible(scope.locator(_APPROVE_BUTTON))
        return approval_status(texts), can_approve

    async def _click_approve(self, page: Page, log: JobLogger) -> bool:
        """
        Click Approve and accept an optional confirmation.

        A native browser dialog is accepted one-shot for the duration of the click; a
        custom Lightning modal is searched for an Approve/Confirm/Yes/OK button. Returns
        ``False`` when the approval control never becomes clickable.
        """
        approve = (await _contract_scope(page)).locator(_APPROVE_BUTTON)
        if not await poll(lambda: _has_count(approve, 1), self._timeout_ms):
            return False
        page.on("dialog", _accept_dialog)
        try:
            if not await click_first_visible(approve, self._timeout_ms):
                return False
            log("apply: lms2_cl_contract: approve clicked")
            await self._confirm_dialog(page)
            return True
        finally:
            page.remove_listener("dialog", _accept_dialog)

    async def _confirm_dialog(self, page: Page) -> None:
        """
        Confirm the Approve modal that the approval click opens.

        The page's **Approve** button only opens a modal (``div.modal-box``); the actual
        approval is the ``button.btn-approval-approve`` button labelled
        ``✓ Confirm Approval``. That class is tried first; a generic dialog scan is the
        fallback for a page variant. Clicking the approval bar's own Approve button twice
        is impossible because the bar button is not inside a dialog container.
        """
        await page.wait_for_timeout(500)
        scope = await _contract_scope(page)
        confirm = scope.locator(_APPROVE_CONFIRM_BUTTON)
        ready = await poll(lambda: _is_visible(confirm), 10_000)
        if ready and await click_first_visible(confirm, 5000):
            return
        for selector in _DIALOG_SELECTORS:
            dialogs = scope.locator(selector)
            try:
                count = await dialogs.count()
            except Exception as exc:  # noqa: BLE001 - re-render between readers
                logger.debug("lms approval dialog lookup failed: %s", exc)
                continue
            for index in range(count):
                dialog = dialogs.nth(index)
                if not await _is_visible(dialog):
                    continue
                for name in _CONFIRM_BUTTON_NAMES:
                    confirm = dialog.get_by_role("button", name=name, exact=False)
                    if await _is_visible(confirm):
                        try:
                            await confirm.first.click(timeout=2000)
                        except Exception as exc:  # noqa: BLE001 - overlay may close
                            logger.debug("lms approval confirm click failed: %s", exc)
                        return
                continue

    async def _is_approved(self, page: Page) -> bool:
        """Whether the contract header now reports an approved state."""
        status, _ = await self._approval_state(page)
        return approval_action(status, False) is ApprovalAction.PROCEED

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

    async def _open_modification(self, page: Page, log: JobLogger) -> bool:
        """Expand LOAN QUICK ACTIONS and open the Contract Modification form."""
        if await page.locator("div.mod-shell").count() > 0:
            return True
        trigger = page.locator('button.nav-section-trigger[data-group="loanactions"]')
        log("apply: lms2_cl_contract: expanding LOAN QUICK ACTIONS")
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
        self, page: Page, targets: Sequence[FieldTarget], log: JobLogger
    ) -> dict[FieldTarget, str | None]:
        """Read Property Value from the Financials card (view or edit mode)."""
        values: dict[FieldTarget, str | None] = {}
        for target in targets:
            name = describe_target(target)
            log(f"read: lms2_collateral: {name}: locating field")
            raw = await self._read_view(page, target)
            if raw is None:
                input_locator = page.locator(
                    f'lightning-input[data-field="{_COLLATERAL_PROPERTY_FIELD}"] input'
                )
                if await input_locator.count() > 0:
                    raw = await input_locator.first.input_value(
                        timeout=self._timeout_ms
                    )
            values[target] = raw
            log(f"read: lms2_collateral: {name}={raw!r}")
        return values

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str], log: JobLogger
    ) -> dict[FieldTarget, WriteOutcome]:
        """Click Edit, fill Property Value, click Save and verify the read-back."""
        outcomes: dict[FieldTarget, WriteOutcome] = {}
        edit = page.get_by_role("button", name="Edit", exact=True)
        log("apply: lms2_collateral: opening edit form")
        if not await click_first_visible(edit, self._timeout_ms):
            log("apply: lms2_collateral: Edit did not become clickable")
            return {target: WriteOutcome.UNKNOWN for target in values}
        input_locator = page.locator(
            f'lightning-input[data-field="{_COLLATERAL_PROPERTY_FIELD}"] input'
        )
        if not await poll(lambda: _has_count(input_locator, 1), self._timeout_ms):
            log("apply: lms2_collateral: edit input did not appear")
            return {target: WriteOutcome.UNKNOWN for target in values}
        try:
            for target, value in values.items():
                name = describe_target(target)
                log(f"apply: lms2_collateral: {name}: filling {value!r}")
                actual = await clear_and_fill(
                    input_locator.first, value, self._timeout_ms
                )
                if not _same_amount(actual, value):
                    log(
                        f"apply: lms2_collateral: {name}: input reads {actual!r}; "
                        f"expected {value!r}"
                    )
                    return {
                        pending: WriteOutcome.UNKNOWN for pending in values
                    }
                log(f"apply: lms2_collateral: {name}: filled {value!r}")
                outcomes[target] = WriteOutcome.SAVED
            save = page.get_by_role("button", name="Save", exact=True)
            log("apply: lms2_collateral: clicking Save")
            if not await click_first_visible(save, self._timeout_ms):
                log("apply: lms2_collateral: Save did not become clickable")
                return {target: WriteOutcome.UNKNOWN for target in values}
            log("apply: lms2_collateral: Save clicked")
            for target, value in values.items():
                name = describe_target(target)
                saved = await poll(
                    partial(self._saved, page, target, value),
                    self._timeout_ms,
                )
                outcomes[target] = (
                    WriteOutcome.SAVED if saved else WriteOutcome.REJECTED
                )
                log(
                    f"apply: lms2_collateral: {name}: "
                    f"{'saved' if saved else 'read-back did not match'}"
                )
            return outcomes
        except Exception as exc:  # noqa: BLE001 - page may re-render mid-save
            logger.debug("lms collateral write failed: %s", exc)
            log(f"apply: lms2_collateral: error {type(exc).__name__}: {exc}")
            return {target: WriteOutcome.UNKNOWN for target in values}

    async def _read_view(self, page: Page, target: FieldTarget) -> str | None:
        """
        Read the Financials stat value in view mode.

        Find the exact ``div.stat-label`` first, then its ``div.stat-item`` parent and
        the sibling ``.stat-value``. Filtering whole stat rows by text can match a
        container with several values; matching the label element avoids reading or
        writing a concatenated amount.
        """
        edit_input = page.locator(
            f'lightning-input[data-field="{_COLLATERAL_PROPERTY_FIELD}"] input'
        )
        if await edit_input.count() > 0:
            # Still in edit mode; the caller reads the input value directly. Reading
            # the stat value here can concatenate the input and the hidden display.
            return None
        label = page.locator("div.stat-label", has_text=target.label).first
        if not await poll(lambda: _has_count(label, 1), self._timeout_ms):
            return None
        stat = label.locator("xpath=ancestor::div[contains(@class,'stat-item')][1]")
        if await stat.count() == 0:
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


async def _is_visible(locator: Locator) -> bool:
    """Whether the locator has a visible match; a re-render reads as ``False``."""
    try:
        return await locator.count() > 0 and await locator.first.is_visible()
    except Exception as exc:  # noqa: BLE001 - detached during a re-render
        logger.debug("visibility read failed: %s", exc)
        return False


async def _contract_scope(page: Page) -> Locator:
    """The CL contract component, or the whole page before it has rendered.

    Scoping the approval pills, button and dialogs to ``c-cl-contract-detail`` keeps an
    unrelated Lightning status pill or modal elsewhere on the page out of the decision.
    """
    host = page.locator(_CONTRACT_HOST)
    return host if await _is_visible(host) else page.locator("html")


async def _accept_dialog_async(dialog: Dialog) -> None:
    """Accept a native browser dialog, logging a failure that arrives too late."""
    try:
        await dialog.accept()
    except Exception as exc:  # noqa: BLE001 - dialog may already be gone
        logger.debug("native dialog accept failed: %s", exc)


_DIALOG_TASKS: set[asyncio.Task[None]] = set()


def _accept_dialog(dialog: Dialog) -> None:
    """Schedule acceptance from Playwright's synchronous dialog callback."""
    task = asyncio.create_task(_accept_dialog_async(dialog))
    _DIALOG_TASKS.add(task)
    task.add_done_callback(_DIALOG_TASKS.discard)


async def _open_lms_tab(page: Page, timeout_ms: int) -> None:
    """Wait for and click the LMS tab on the opportunity page."""
    tab = page.locator(_LMS_TAB)
    deadline = Deadline(timeout_ms)
    while not deadline.expired:
        try:
            if await bounded(tab.count, deadline) > 0:
                break
        except TimeoutError:
            return
        await page.wait_for_timeout(max(0, min(500, deadline.remaining_ms())))
    try:
        if await bounded(tab.count, deadline) > 0 and await tab.first.get_attribute(
            "aria-selected", timeout=deadline.action_ms()
        ) != "true":
            await tab.first.click(timeout=deadline.action_ms())
            await page.wait_for_timeout(1000)
    except TimeoutError:
        return
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


async def _await_lms_rows(
    page: Page, host_tag: str, timeout_ms: int
) -> list[LmsRow] | None:
    """
    The component renders after the tab click; poll until it settles.

    Returns the rows it renders, ``[]`` when the component itself says it has no
    records, and ``None`` when neither happened before the budget expired. ``None``
    must be reported as unresolved: a component that never rendered is not empty.
    """
    deadline = Deadline(timeout_ms)
    while not deadline.expired:
        try:
            rows = await bounded(lambda: _scrape_lms_rows(page, host_tag), deadline)
        except TimeoutError:
            return None
        if rows:
            return rows
        try:
            empty = await bounded(lambda: _lms_shows_empty(page, host_tag), deadline)
        except TimeoutError:
            return None
        if empty:
            return []
        await page.wait_for_timeout(max(0, min(1000, deadline.remaining_ms())))
    return None


#: Shadow-DOM text a rendered LMS 2.0 list uses when it has no records.
_LMS_EMPTY_JS = """
(hostTag) => {
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
    if (!host || !host.shadowRoot) return false;
    const text = (host.shadowRoot.textContent || '').trim();
    return /no\\s+(records|data|items|contracts|loans)/i.test(text);
}
"""


async def _lms_shows_empty(page: Page, host_tag: str) -> bool:
    """Whether the rendered component says it has no records (positive empty)."""
    try:
        raw = await page.evaluate(_LMS_EMPTY_JS, host_tag)
    except Exception as exc:  # noqa: BLE001 - component not rendered yet
        logger.debug("LMS empty check failed for %s: %s", host_tag, exc)
        return False
    return raw is True


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
