"""Extraction strategies for Salesforce Lightning list views."""
import re
from typing import Any, Dict, Optional

from playwright.sync_api import Page

from . import config


def _text_matches(page, pattern: str):
    import re as _re
    return set(_re.findall(pattern, "\n".join(page.get_by_text(_re.compile(pattern)).all_text_contents())))


def collect_matches(page: Page, pattern: str, retries: int = 3):
    """Values matching `pattern` visible right now. Uses Playwright's text
    engine, which pierces Lightning's lockered LWC DOM (plain JS cannot)."""
    import re
    rx = re.compile(pattern)
    for attempt in range(retries):
        try:
            texts = page.get_by_text(rx).all_text_contents()
            return {m for t in texts for m in rx.findall(t)}
        except Exception:
            page.wait_for_timeout(1000)
    return set()


def read_item_total(page: Page) -> Optional[int]:
    """Parse N from the list header: '20 items • Sorted by ...'."""
    try:
        txt = page.get_by_text(re.compile(r"\d+\s+items?\s+[•·]")).first.inner_text()
        m = re.search(r"(\d+)\s+item", txt)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def wait_for_data(page: Page, pattern: str, timeout_s: float = 60) -> set:
    import time
    deadline = time.time() + timeout_s
    nums: set = set()
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        nums = collect_matches(page, pattern)
        if nums:
            return nums
    return nums


def extract_via_printable_view(page: Page, ctx, pattern: str) -> set:
    """Click 'Printable View'; popup renders ALL rows without virtualization."""
    try:
        btn = page.get_by_role("button", name="Printable View")
        if btn.count() == 0:
            return set()
        with ctx.expect_page(timeout=25_000) as popup_info:
            btn.first.click()
        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded", timeout=40_000)
        nums: set = set()
        stable = 0
        for _ in range(40):
            popup.wait_for_timeout(1500)
            batch = collect_matches(popup, pattern)
            if batch and batch == nums:
                stable += 1
            else:
                stable = 0
            nums |= batch
            if stable >= 3 and nums:
                break
        popup.close()
        return nums
    except Exception:
        return set()


def click_show_more(page: Page, max_clicks: int = 300) -> int:
    """Lightning paginates some list views with a 'Show more' action at the
    bottom of the table. Keep clicking it (text-engine locators, per the
    shadow-DOM constraint) until it disappears or stops yielding. Returns
    number of successful clicks."""
    import re
    more_rx = re.compile(r"^\s*Show more\s*$", re.IGNORECASE)
    clicked = 0
    while clicked < max_clicks:
        locators = [
            page.get_by_role("button", name=more_rx),
            page.get_by_text(more_rx),
        ]
        more = None
        for loc in locators:
            try:
                if loc.count() > 0:
                    more = loc.first
                    break
            except Exception:
                continue
        if more is None:
            break
        try:
            more.click(timeout=5000)
            clicked += 1
            page.wait_for_timeout(2500)  # let the next chunk render
        except Exception:
            break
    return clicked


def extract_via_scroll(page: Page, pattern: str, target: Optional[int] = None,
                       max_idle_rounds: int = 4) -> set:
    """Fallback: drain pagination ('Show more' chunks + virtualized scroll)
    until the table stops yielding rows."""
    numbers: set = set()
    idle = 0
    rounds = 0
    while idle < max_idle_rounds:
        rounds += 1
        page.keyboard.press("End")
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(2500)
        if target is None or len(numbers) < target:
            if click_show_more(page, max_clicks=1):
                idle = 0
                continue
        from .extractors import collect_matches  # self-import safe
        new = collect_matches(page, pattern)
        added = len(new - numbers)
        numbers |= new
        if target is not None and len(numbers) >= target:
            break
        idle = idle + 1 if added == 0 else 0
    click_show_more(page)  # final drain: make sure nothing is left behind
    final = collect_matches(page, pattern)
    numbers |= final
    return numbers


def parse_description_fields(description: str) -> Dict[str, Optional[str]]:
    """Parse the 4 workflow fields out of the 'Loan Deviation Description'
    block. Lines look like 'Property Value ... -68,37,600', 'Tenure (Yrs)-20.0',
    'EMI-38,538', 'Loan Amount-...'. Anchored to line starts so
    'EMI-38,538' and 'EMIs & other fixed pmts ...' don't collide."""
    def grab(rx: str) -> Optional[str]:
        m = re.search(rx, description, re.MULTILINE)
        return m.group(1).strip() or None if m else None

    return {
        "property_value": grab(r"(?m)^\s*Property Value[^-\n]*-\s?(.+)$"),
        "loan_amount": grab(r"(?m)^\s*Loan Amount[^-\n]*-\s?(.+)$"),
        "tenure": grab(r"(?m)^\s*Tenure[^-\n]*-\s?(.+)$"),
        # 'EMI and other fixed payments including HFFC Loan' — matches both
        # 'EMIs & other fixed pmts inc HFFC Loan-82,325' and
        # 'EMIs & other HFFC Loan - 39,995'. The bare 'EMI-…' line is the
        # pre-calculated EMI and must NOT land in this field.
        "emi": grab(r"(?m)^\s*EMIs?\s*&[^-\n]*-\s?(.+)$"),
    }


def clean_description(raw: str) -> str:
    """Strip the section-label echoes Lightning injects around the value."""
    drop = (r"^\s*(Help |Edit |)?Loan Deviation Description\s*$",
            r"^\s* Help Loan Deviation Description\s*$")
    lines = [ln.rstrip() for ln in raw.splitlines()]
    lines = [ln for ln in lines
             if ln and not any(re.match(pat, ln, re.IGNORECASE) for pat in drop)]
    return "\n".join(lines).strip()


def collect_record_links(page: Page, pattern: str, target: Optional[int] = None):
    """Map deviation number -> record URL from the list view. Playwright role/
    attribute engines pierce the lockered DOM for hrefs. Drains the list
    (clicks Show more + scrolls) until every matching row has a link."""
    rx = re.compile(pattern)
    found: Dict[str, str] = {}
    idle = 0
    rounds = 0
    while idle < 4:
        rounds += 1
        links = page.get_by_role("link")
        n = links.count()
        for i in range(n):
            try:
                loc = links.nth(i)
                txt = loc.inner_text(timeout=1000) or ""
                m = rx.search(txt)
                if not m:
                    continue
                href = loc.get_attribute("href")
                if href and "/lightning/r/" in href:
                    found.setdefault(m.group(0).strip(), href)
            except Exception:
                continue
        if target is not None and len(found) >= target:
            break
        if click_show_more(page, max_clicks=1):
            idle = 0
            continue
        page.keyboard.press("End")
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(2500)
        previous = len(found)
        # recount links after scroll
        links = page.get_by_role("link")
        for i in range(links.count()):
            try:
                loc = links.nth(i)
                txt = loc.inner_text(timeout=1000) or ""
                m = rx.search(txt)
                if not m:
                    continue
                href = loc.get_attribute("href")
                if href and "/lightning/r/" in href:
                    found.setdefault(m.group(0).strip(), href)
            except Exception:
                continue
        idle = idle + 1 if len(found) <= previous else 0
    return found


def scrape_record_detail(sfsession, record_path: str) -> Optional[Dict[str, Any]]:
    """Open one deviation record; extract the 'Loan Deviation Description'
    block + page refs (other pages linked from this record that the update
    workflow must visit). Returns a dict for upsert_deviation_detail."""
    import re as _re
    url = record_path if record_path.startswith("http") else \
        f"{config.ORG_BASE}{record_path}"
    page = sfsession.open(url, wait=3)
    page.wait_for_timeout(7000)

    try:
        page.get_by_text("Dismiss", exact=True).first.click(timeout=2000)
    except Exception:
        pass  # guidance panel overlay — optional

    label = page.get_by_text("Loan Deviation Description", exact=True).first
    try:
        label.wait_for(timeout=15_000)
    except Exception:
        return None

    # the section body = the ancestor that carries the full text
    body = None
    for depth in (3, 4, 5, 6):
        try:
            t = label.locator(f"xpath=ancestor-or-self::*[{depth}]") \
                .inner_text(timeout=2500).strip()
        except Exception:
            continue
        if t and len(t) > len("Loan Deviation Description") * 2 and \
                "Loan Deviation Description" in t:
            body = t
            if len(t) > 120:
                break
    description = clean_description(body or "")

    # page refs: every in-org record link on this page (Opportunity, SD
    # contract, ...). Dedup by href; labels from link text where usable.
    refs: Dict[str, Dict[str, str]] = {}
    links = page.get_by_role("link")
    n = links.count()
    for i in range(n):
        try:
            loc = links.nth(i)
            href = loc.get_attribute("href") or ""
            if not href or ("/lightning/r/" not in href and
                            "/lightning/o/" not in href):
                continue
            txt = (loc.inner_text(timeout=800) or "").strip()
            name = txt or href
            key = href.split("?")[0].rstrip("/")
            if key not in refs and name:
                if "/lightning/r/Opportunity/" in key:
                    kind = "opportunity"
                elif "/lightning/r/Consumer_Loan_Deviation__c/" in key:
                    kind = "deviation"
                else:
                    kind = "related"
                # Lightning stores hrefs relative; store absolute so UI links
                # leave the app instead of 404ing against our API
                url_abs = href if href.startswith("http") else \
                    f"{config.ORG_BASE}{href}"
                refs[key] = {"name": name[:80], "kind": kind, "url": url_abs}
        except Exception:
            continue

    fields = parse_description_fields(description)
    return {
        "record_id": url.rstrip("/").split("/")[-1],
        "record_url": url,
        "description": description,
        "property_value": fields["property_value"],
        "loan_amount": fields["loan_amount"],
        "tenure": fields["tenure"],
        # EMI is NOT populated automatically: the description's EMI is the
        # pre-calculated one; "EMI in HFFC" is entered by the human in the deck.
        "emi": None,
        "page_refs": list(refs.values()),
    }


def extract_list_view(sfsession, url: str, pattern: str, *, object_name: str = "records"):
    """Full strategy for one list-view URL. Returns (numbers, header_total).

    Raises SessionExpired if the injected session is no longer valid.
    """
    from .browser import SessionExpired

    page = sfsession.open(url, wait=4)
    if not _looks_logged_in(page):
        raise SessionExpired(f"not logged in for {url}")

    first = wait_for_data(page, pattern)
    total = read_item_total(page)
    numbers = extract_via_printable_view(page, sfsession.ctx, pattern)
    if not numbers:
        numbers = extract_via_scroll(page, pattern, target=total)
    return numbers, total


def _looks_logged_in(page: Page) -> bool:
    url = page.url
    return "/lightning/" in url and "login" not in url.lower()
