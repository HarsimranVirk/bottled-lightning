"""Run updater strategies for a deviation."""

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.types import JsonValue

from .strategies import UpdateResult


def orchestrate(
    profile: WorkflowProfile,
    session: SalesforceSession,
    page_refs: list[dict[str, JsonValue]],
    params: dict[str, JsonValue],
) -> list[UpdateResult]:
    # TODO: map page_refs by kind to updater strategies and run them
    return []
