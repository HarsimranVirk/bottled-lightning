"""Updater strategy protocol."""

from dataclasses import dataclass
from typing import Protocol

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.types import JsonValue


@dataclass
class UpdateResult:
    success: bool
    detail: str = ""


class UpdaterStrategy(Protocol):
    name: str

    def update(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        ref_url: str,
        params: dict[str, JsonValue],
    ) -> UpdateResult: ...
