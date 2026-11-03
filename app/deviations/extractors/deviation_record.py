"""Deviation record-page extraction: description, housing ROI, page refs."""

from playwright.sync_api import Page

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.deviations.types import ScrapedDetail

from ... import config as _cfg
from .common import clean_description, parse_description_fields

_HOUSING_ROI_SELECTORS = {
    "requested_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Requested_ROI__c",
    "ideal_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Ideal_ROI_Formula__c",
    "updated_roi": "sfdc:RecordField.Consumer_Loan_Deviation__c.Updated_ROI__c",
    "requested_variance": "sfdc:RecordField.Consumer_Loan_Deviation__c.Requested_Variance__c",
}


def _housing_roi_field_value(page: Page, selection_name: str) -> str | None:
    loc = page.locator(f'[data-target-selection-name="{selection_name}"]')
    if loc.count() == 0:
        return None
    first = loc.first
    fn = first.locator("lightning-formatted-number")
    if fn.count() > 0:
        try:
            txt = fn.first.inner_text(timeout=2000).strip()
        except Exception:  # noqa: BLE001
            txt = ""
        if txt:
            return txt
    ctrl = first.locator(".slds-form-element__control")
    if ctrl.count() > 0:
        try:
            txt = ctrl.first.inner_text(timeout=2000).strip()
        except Exception:  # noqa: BLE001
            txt = ""
        if txt and not txt.lower().startswith("edit "):
            return txt
    return None


def scrape_deviation_record_detail(
    profile: WorkflowProfile, session: SalesforceSession, record_path: str
) -> ScrapedDetail | None:
    url = record_path if record_path.startswith("http") else f"{_cfg.ORG_BASE}{record_path}"
    page = session.open(url, wait=2)

    try:
        dismiss = page.get_by_text("Dismiss", exact=True).first
        if dismiss.count() > 0 and dismiss.is_visible():
            dismiss.click(timeout=2000)
    except Exception as e:  # noqa: BLE001
        print(f"! suppressed exception: {e}", file=__import__("sys").stderr)

    label = page.get_by_text("Loan Deviation Description", exact=True).first
    try:
        label.wait_for(timeout=10_000)
    except Exception:  # noqa: BLE001
        return None

    body = None
    for depth in (3, 4, 5, 6):
        try:
            t = (
                label.locator(f"xpath=ancestor-or-self::*[{depth}]")
                .inner_text(timeout=2500)
                .strip()
            )
        except Exception as e:  # noqa: BLE001
            print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
            continue
        if (
            t
            and len(t) > len("Loan Deviation Description") * 2
            and "Loan Deviation Description" in t
        ):
            body = t
            if len(t) > 120:
                break
    description = clean_description(body or "")

    # Wait briefly for the Opportunity link to render.
    for _ in range(10):
        try:
            if page.get_by_role("link").count() >= 3:
                break
        except Exception as e:  # noqa: BLE001
            print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
        page.wait_for_timeout(300)
    page.wait_for_timeout(500)

    refs: dict[str, dict[str, str]] = {}
    links = page.get_by_role("link")
    n = links.count()
    for i in range(n):
        try:
            loc = links.nth(i)
            href = loc.get_attribute("href") or ""
            if not href or ("/lightning/r/" not in href and "/lightning/o/" not in href):
                continue
            txt = (loc.inner_text(timeout=800) or "").strip()
            name = txt or href
            key = href.split("?")[0].rstrip("/")
            if key not in refs and name:
                # Only the Opportunity ref is useful on this page.
                if "/lightning/r/Opportunity/" not in key:
                    continue
                kind = "opportunity"
                url_abs = href if href.startswith("http") else f"{_cfg.ORG_BASE}{href}"
                refs[key] = {"name": name[:80], "kind": kind, "url": url_abs}
        except Exception as e:  # noqa: BLE001
            print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
            continue

    fields = parse_description_fields(description)

    section_btn = page.get_by_role("button", name="Housing Loan Deviation Details")
    if section_btn.count() > 0:
        try:
            if section_btn.first.get_attribute("aria-expanded") != "true":
                section_btn.first.click(timeout=5000)
                page.wait_for_timeout(1000)
        except Exception as e:  # noqa: BLE001
            print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
    for _ in range(10):
        if (
            page.locator(
                '[data-target-selection-name="sfdc:RecordField.Consumer_Loan_Deviation__c.Ideal_ROI_Formula__c"]'
            ).count()
            > 0
        ):
            break
        page.wait_for_timeout(300)

    housing_values = {
        key: _housing_roi_field_value(page, selector)
        for key, selector in _HOUSING_ROI_SELECTORS.items()
    }

    opportunity_url = next((r["url"] for r in refs.values() if r["kind"] == "opportunity"), None)

    return ScrapedDetail(
        record_id=url.rstrip("/").split("/")[-1],
        record_url=url,
        description=description,
        property_value=fields["property_value"],
        loan_amount=fields["loan_amount"],
        tenure=fields["tenure"],
        emi=None,
        requested_roi=housing_values["requested_roi"],
        ideal_roi=housing_values["ideal_roi"],
        updated_roi=housing_values["updated_roi"],
        requested_variance=housing_values["requested_variance"],
        page_refs=list(refs.values()),
        opportunity_url=opportunity_url,
        skip=False,
        skip_reason=None,
    )
