"""Collect deviation number -> record URL mapping from the list view."""

from collections.abc import Callable

from app.browser import SalesforceSession
from app.deviations.types import State

from ...base import WorkflowProfile
from .. import list_view
from .protocol import StrategyResult


class DeviationRecordLinksStrategy:
    name = "deviation_record_links"

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult:
        result = StrategyResult()
        page = session.require_page()
        _nums = state.numbers
        links = list_view.collect_record_links(page, profile.pattern, target=len(_nums))
        state.links = links
        log(f"record links mapped: {len(links)}")
        return result
