"""CL contract updater strategy (stub)."""

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.types import JsonValue

from . import UpdateResult, UpdaterStrategy


class ClContractUpdater(UpdaterStrategy):
    name = "cl_contract"

    def update(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        ref_url: str,
        params: dict[str, JsonValue],
    ) -> UpdateResult:
        return UpdateResult(success=True, detail="not implemented")
