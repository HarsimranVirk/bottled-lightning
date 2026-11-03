"""Scrape each deviation record page (description, housing ROI, page refs)."""

from collections.abc import Callable

from app.browser import SalesforceSession
from app.deviations.types import DetailEntry, ScrapedDetail, State

from ...base import WorkflowProfile
from .. import deviation_record
from .protocol import StrategyResult


class DeviationRecordDetailStrategy:
    name = "deviation_record_detail"

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult:
        result = StrategyResult()
        details: list[DetailEntry] = []
        links = state.links
        for value, href in sorted(links.items()):
            det = deviation_record.scrape_deviation_record_detail(profile, session, href)
            if det is None:
                log(f"no detail for {value}")
                state.failed = state.failed + 1
                reason: str | None = (
                    f"skipped due to SF internal error: {self.name}: no detail for {value}"
                )
                result.skip_reason = result.skip_reason or reason
                details.append(
                    DetailEntry(
                        value=value,
                        det=ScrapedDetail(),
                        refs=[],
                        skip=True,
                        skip_reason=reason,
                        opportunity_url=None,
                        opportunity_product_type=None,
                    )
                )
                continue
            skip = bool(det.skip)
            reason = det.skip_reason
            refs = list(det.page_refs)
            opp_url = det.opportunity_url
            if opp_url is None:
                opp_url = next(
                    (
                        str(r.get("url"))
                        for r in refs
                        if isinstance(r, dict) and r.get("kind") == "opportunity"
                    ),
                    None,
                )
            # remove transient fields from det so upsert gets clean detail
            det.page_refs = []
            det.opportunity_url = None
            det.skip = False
            det.skip_reason = None
            details.append(
                DetailEntry(
                    value=value,
                    det=det,
                    refs=refs,
                    skip=skip,
                    skip_reason=reason,
                    opportunity_url=opp_url,
                    opportunity_product_type=None,
                )
            )
            if skip:
                state.skipped = state.skipped + 1
                log(f"skipped {value}: {reason}")
            else:
                log(f"picked {value}")
        state.details = details
        return result
