"""Open the Opportunity page once per deviation and cache its product type."""

from collections.abc import Callable

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.deviations.types import State

from .. import opportunity
from .protocol import StrategyResult


class OpportunityContextStrategy:
    name = "opportunity_context"

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult:
        result = StrategyResult()
        product_cache = state.product_cache
        state.product_cache = product_cache
        for detail in state.details:
            if detail.skip:
                continue
            opp_url = detail.opportunity_url
            if not isinstance(opp_url, str) or not opp_url:
                continue
            page = session.require_page()
            if page.url != opp_url:
                page = session.open(opp_url, wait=2)
            if opp_url not in product_cache:
                product_cache[opp_url] = opportunity.read_opportunity_product_type(session, opp_url)
            detail.opportunity_product_type = product_cache[opp_url]
            log(f"opportunity context: {product_cache[opp_url]}")
        return result
