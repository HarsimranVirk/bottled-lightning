"""Composite pattern: combine multiple extractor strategies into one."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.deviations.types import State

from .protocol import StrategyResult


class _HasExtract(Protocol):
    name: str

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult: ...


@dataclass
class CompositeExtractorStrategy:
    name: str
    children: list[_HasExtract] = field(default_factory=list)

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult:
        result = StrategyResult()
        for child in self.children:
            try:
                r = child.extract(profile, session, state, log)
                result.refs.extend(r.refs)
                if r.skip_reason and result.skip_reason is None:
                    result.skip_reason = r.skip_reason
            except Exception as e:  # noqa: BLE001 - isolate broken strategies
                log(f"{getattr(child, 'name', child)} failed: {type(e).__name__}: {e}")
                if result.skip_reason is None:
                    result.skip_reason = (
                        f"skipped due to SF internal error: "
                        f"{getattr(child, 'name', child)}: {type(e).__name__}: {e}"
                    )
        return result
