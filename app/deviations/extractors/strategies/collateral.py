"""Collateral ref extraction from the opportunity page."""

from collections.abc import Callable

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.deviations.types import State

from .... import config as _app_config
from .protocol import StrategyResult


class CollateralStrategy:
    name = "collateral"

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

            related_url = opp_url.replace("/view", "/related/Collateral__r/view")
            tab = session.open_tab(related_url, wait=2)
            try:
                rows = tab.locator("tr.slds-hint-parent")
                count = rows.count()

                if count > 1:
                    reason = f"skipped due to SF ambiguity: multiple collateral objects ({count})"
                    detail.skip = True
                    detail.skip_reason = reason
                    state.skipped = state.skipped + 1
                    log(reason)
                    result.skip_reason = result.skip_reason or reason
                    continue
                if count == 1:
                    row = rows.nth(0)
                    link_loc = row.get_by_role("link")
                    cid = ""
                    href = ""
                    for j in range(link_loc.count()):
                        t = (link_loc.nth(j).inner_text(timeout=500) or "").strip()
                        h = link_loc.nth(j).get_attribute("href") or ""
                        if h and "/lightning/r/" in h:
                            cid = t or cid
                            href = h
                    if href:
                        abs_url = (
                            href if href.startswith("http") else f"{_app_config.ORG_BASE}{href}"
                        )
                        detail.refs = detail.refs + [
                            {"name": cid, "kind": "collateral", "url": abs_url}
                        ]
                        result.refs.append({"name": cid, "kind": "collateral", "url": abs_url})
                        log(f"collateral ref: {cid}")
                else:
                    log("no collateral found")
            finally:
                try:
                    tab.close()
                except Exception as e:  # noqa: BLE001
                    print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
        return result
