"""Extractor strategy protocol + result."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.deviations.types import State


@dataclass
class StrategyResult:
    refs: list[dict[str, str]] = field(default_factory=list)
    skip_reason: str | None = None


class ExtractorStrategy(Protocol):
    name: str

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult: ...
