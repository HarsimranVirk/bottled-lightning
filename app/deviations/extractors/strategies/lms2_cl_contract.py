"""LMS 2.0 CL contract ref extraction from the opportunity page."""

from collections.abc import Callable

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.deviations.types import State

from .lms2_collateral import _scrape_lms_rows
from .protocol import StrategyResult


class LMS2ClContractStrategy:
    name = "lms2_cl_contract"

    def extract(
        self,
        profile: WorkflowProfile,
        session: SalesforceSession,
        state: State,
        log: Callable[[str], None],
    ) -> StrategyResult:
        result = StrategyResult()
        for detail in state.details:
            if detail.skip:
                continue
            opp_url = detail.opportunity_url
            if not isinstance(opp_url, str) or not opp_url:
                continue

            page = session.require_page()
            if page.url != opp_url:
                page = session.open(opp_url, wait=2)
            try:
                tab = page.locator('a[data-tab-value="flexipage_tab2"]')
                if tab.count() > 0 and tab.first.get_attribute("aria-selected") != "true":
                    tab.first.click(timeout=5000)
                    page.wait_for_timeout(1000)
            except Exception as e:  # noqa: BLE001
                print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
            try:
                page.evaluate(
                    "() => { const e=document.getElementById('auraError'); if(e) e.remove(); }"
                )
            except Exception as e:  # noqa: BLE001
                print(f"! suppressed exception: {e}", file=__import__("sys").stderr)

            rows = _scrape_lms_rows(page, "c-lms-cl-contract-related-list")
            if len(rows) > 1:
                reason = f"skipped due to SF ambiguity: multiple LMS2 CL contracts ({len(rows)})"
                detail.skip = True
                detail.skip_reason = reason
                state.skipped = state.skipped + 1
                log(reason)
                result.skip_reason = result.skip_reason or reason
                continue
            if len(rows) == 1:
                row = rows[0]
                uuid = row.get("data_id")
                name = row.get("id_text") or uuid or "LMS2 CL Contract"
                if uuid:
                    url = f"https://hffc.lightning.force.com/lightning/n/CL_Contract_Detail?c__loanId={uuid}"
                    detail.refs = detail.refs + [
                        {"name": str(name), "kind": "lms2_cl_contract", "url": url}
                    ]
                    result.refs.append({"name": str(name), "kind": "lms2_cl_contract", "url": url})
                    log(f"lms2_cl_contract ref: {name}")
            else:
                log("no LMS2 CL contract found")
        return result
