"""Deviation list-view extraction strategy."""

from collections.abc import Callable

from app.browser import SalesforceSession
from app.deviations.types import State

from ...base import WorkflowProfile
from .. import list_view
from .protocol import StrategyResult


class DeviationListViewStrategy:
    name = "deviation_list_view"

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult:
        result = StrategyResult()
        numbers, total, approval_dates = list_view.extract_list_view(profile, session)
        state.numbers = numbers
        state.total = total
        state.approval_dates = approval_dates
        log(f"extracted {len(numbers)} (header total {total})")
        if total is not None and len(numbers) != total:
            log(f"count mismatch: header={total}, extracted={len(numbers)}")
        return result
