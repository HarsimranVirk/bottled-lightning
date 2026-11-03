from app.browser import SalesforceSession

"""LMS2 CL contract updater strategy (stub)."""

from app.deviations.base import WorkflowProfile
from app.types import JsonValue

from . import UpdateResult, UpdaterStrategy


class Lms2ClContractUpdater(UpdaterStrategy):
    name = "lms2_cl_contract"

    def update(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        ref_url: str,
        params: dict[str, JsonValue],
    ) -> UpdateResult:
        return UpdateResult(success=True, detail="not implemented")
