"""LMS 2.0 collateral ref extraction from the opportunity page."""

from collections.abc import Callable

from playwright.sync_api import Page

from app.browser import SalesforceSession
from app.deviations.base import WorkflowProfile
from app.deviations.types import State

from .protocol import StrategyResult


class LMS2CollateralStrategy:
    name = "lms2_collateral"

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

            rows = _scrape_lms_rows(page, "c-lms-collateral-related-list")
            if len(rows) > 1:
                reason = f"skipped due to SF ambiguity: multiple LMS2 collaterals ({len(rows)})"
                detail.skip = True
                detail.skip_reason = reason
                state.skipped = state.skipped + 1
                log(reason)
                result.skip_reason = result.skip_reason or reason
                continue
            if len(rows) == 1:
                row = rows[0]
                uuid = row.get("data_id")
                name = row.get("id_text") or uuid or "LMS2 Collateral"
                if uuid:
                    url = f"https://hffc.lightning.force.com/lightning/n/Collateral_Detail?c__collateralId={uuid}"
                    detail.refs = detail.refs + [
                        {"name": str(name), "kind": "lms2_collateral", "url": url}
                    ]
                    result.refs.append({"name": str(name), "kind": "lms2_collateral", "url": url})
                    log(f"lms2_collateral ref: {name}")
            else:
                log("no LMS2 collateral found")
        return result


def _scrape_lms_rows(page: Page, host_tag: str) -> list[dict[str, str]]:
    js = """
    (hostTag) => {
        const result = [];
        function findHost(tag, root) {
            const found = root.querySelector ? root.querySelector(tag) : null;
            if (found) return found;
            const els = root.querySelectorAll ? root.querySelectorAll('*') : [];
            for (const el of els) {
                if (el.shadowRoot) {
                    const r = findHost(tag, el.shadowRoot);
                    if (r) return r;
                }
            }
            return null;
        }
        const host = findHost(hostTag, document);
        if (!host || !host.shadowRoot) return result;
        const root = host.shadowRoot;
        const rowEls = root.querySelectorAll(
            'tr.rl-row, tr.data-row, div.contract-row, div.rl-row');
        for (const r of rowEls) {
            const dataId = r.getAttribute('data-id') || '';
            let idText = '';
            const idEl = r.querySelector('span.id-link, span.loan-link');
            if (idEl) idText = (idEl.textContent || '').trim();
            result.push({data_id: dataId, id_text: idText});
        }
        return result;
    }
    """
    try:
        return page.evaluate(js, host_tag) or []
    except Exception as e:  # noqa: BLE001
        print(f"! suppressed exception: {e}", file=__import__("sys").stderr)
        return []
