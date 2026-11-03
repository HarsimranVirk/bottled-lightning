"""Deviation Z2 extraction pipeline (Composite pattern)."""

from collections.abc import Callable

from app.browser import SalesforceSession
from app.deviations.types import DetailEntry, ScrapedDetail, State

from ..deviations.base import WorkflowProfile
from ..deviations.extractors import (
    DeviationListViewStrategy,
    DeviationRecordDetailStrategy,
    DeviationRecordLinksStrategy,
)
from ..deviations.extractors.strategies import (
    CLContractStrategy,
    CollateralStrategy,
    CompositeExtractorStrategy,
    LMS2ClContractStrategy,
    LMS2CollateralStrategy,
    OpportunityContextStrategy,
)

PerDeviationComposite = CompositeExtractorStrategy(
    name="per_deviation",
    children=[
        DeviationRecordDetailStrategy(),
        OpportunityContextStrategy(),
        LMS2CollateralStrategy(),
        LMS2ClContractStrategy(),
        CLContractStrategy(),
        CollateralStrategy(),
    ],
)


def extract_list_and_links(
    profile: WorkflowProfile, session: SalesforceSession, log: Callable[[str], None]
) -> tuple[set[str], int | None, dict[str, str], dict[str, str]]:
    state = State()
    DeviationListViewStrategy().extract(profile, session, state, log)
    DeviationRecordLinksStrategy().extract(profile, session, state, log)
    return state.numbers, state.total, state.links, state.approval_dates


def _cached_entry(value: str, href: str) -> DetailEntry | None:
    from .. import store

    det = store.get_deviation_details(value)
    if not det or not det.get("description"):
        return None
    refs_raw = store.get_deviation_page_refs(value)
    refs = [
        {
            "name": str(r.get("name", "")),
            "kind": str(r.get("kind", "")),
            "url": str(r.get("url", "")),
        }
        for r in refs_raw
    ]
    kinds = {r["kind"] for r in refs}
    needed = {"opportunity", "cl_contract", "collateral", "lms2_collateral", "lms2_cl_contract"}
    if not needed.issubset(kinds):
        return None
    opp_url = next((str(r["url"]) for r in refs if r["kind"] == "opportunity"), None)
    return DetailEntry(
        value=value,
        det=ScrapedDetail(
            record_id=det.get("record_id"),
            record_url=det.get("record_url") or href,
            description=det.get("description"),
            property_value=det.get("property_value"),
            loan_amount=det.get("loan_amount"),
            tenure=det.get("tenure"),
            emi=det.get("emi"),
            requested_roi=det.get("requested_roi"),
            ideal_roi=det.get("ideal_roi"),
            updated_roi=det.get("updated_roi"),
            requested_variance=det.get("requested_variance"),
            opportunity_url=det.get("opportunity_url"),
            cl_contract_url=det.get("cl_contract_url"),
            collateral_url=det.get("collateral_url"),
            lms2_collateral_url=det.get("lms2_collateral_url"),
            lms2_cl_contract_url=det.get("lms2_cl_contract_url"),
        ),
        refs=refs,
        skip=False,
        skip_reason=None,
        opportunity_url=opp_url,
        cl_contract_url=det.get("cl_contract_url"),
        collateral_url=det.get("collateral_url"),
        lms2_collateral_url=det.get("lms2_collateral_url"),
        lms2_cl_contract_url=det.get("lms2_cl_contract_url"),
        opportunity_product_type=None,
    )


def extract_one_deviation(
    profile: WorkflowProfile,
    session: SalesforceSession,
    value: str,
    href: str,
    log: Callable[[str], None],
) -> DetailEntry:
    cached = _cached_entry(value, href)
    if cached is not None:
        log(f"cached (skipped browser work): {value}")
        return cached
    state = State(links={value: href})
    PerDeviationComposite.extract(profile, session, state, log)
    details = state.details
    entry: DetailEntry | None = details[0] if details else None
    if entry is None:
        return DetailEntry(
            value=value,
            det=ScrapedDetail(),
            refs=[],
            skip=True,
            skip_reason="skipped due to SF internal error: no detail",
        )
    if not entry.value:
        entry.value = value
    if state.skip_reason and not entry.skip_reason:
        entry.skip_reason = state.skip_reason
        entry.skip = True
    return entry


def run(
    profile: WorkflowProfile, session: SalesforceSession, job_id: int, log: Callable[[str], None]
) -> State:
    numbers, total, links, _approval_dates = extract_list_and_links(profile, session, log)
    details: list[DetailEntry] = []
    for value, href in sorted(links.items()):
        entry = extract_one_deviation(profile, session, value, href, log)
        details.append(entry)
    return State(
        numbers=numbers,
        total=total,
        links=links,
        details=details,
        skip_reason=None,
        skipped=0,
        failed=0,
    )
