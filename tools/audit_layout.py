"""Fail when a screen needs horizontal scrolling at the three review widths.

    .venv/bin/python tools/audit_layout.py --url http://localhost:8765

Checks Home, the review deck, the list view, Jobs and one item detail at 390, 768 and
1280 px. Any element that extends past the viewport, or a document wider than the
viewport, is reported and makes the command exit non-zero. Dev-only; not shipped.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import Page, sync_playwright

_AUDIT_JS = """() => {
    const doc = document.documentElement;
    const viewport = doc.clientWidth;
    const offenders = [];
    for (const element of document.querySelectorAll('*')) {
        const box = element.getBoundingClientRect();
        if (box.width === 0 && box.height === 0) continue;
        if (box.right > viewport + 1 || box.left < -1) {
            offenders.push({
                tag: element.tagName.toLowerCase(),
                classes: typeof element.className === 'string' ? element.className : '',
                left: Math.round(box.left),
                right: Math.round(box.right),
            });
        }
    }
    return { viewport, scrollWidth: doc.scrollWidth, offenders };
}"""


def _report(page: Page) -> tuple[int, int, list[str]]:
    """Return ``(viewport, scroll_width, offender descriptions)`` for the open page."""
    raw = page.evaluate(_AUDIT_JS)
    if not isinstance(raw, dict):
        raise TypeError("layout audit returned an unexpected payload")
    viewport = raw.get("viewport")
    scroll_width = raw.get("scrollWidth")
    offenders = raw.get("offenders")
    if not isinstance(viewport, int) or not isinstance(scroll_width, int):
        raise TypeError("layout audit payload is missing numbers")
    descriptions: list[str] = []
    if isinstance(offenders, list):
        for item in offenders[:8]:
            if not isinstance(item, dict):
                continue
            tag = item.get("tag")
            classes = item.get("classes")
            left = item.get("left")
            right = item.get("right")
            descriptions.append(
                f"{tag if isinstance(tag, str) else '?'}"
                f"{'.' + classes if isinstance(classes, str) and classes else ''}"
                f" [{left}, {right}]"
            )
    return viewport, scroll_width, descriptions


def _first_item_key(base_url: str) -> str | None:
    """One real item key for the detail route; ``None`` when the API is empty."""
    try:
        with urllib.request.urlopen(
            f"{base_url}/api/deviations?limit=1", timeout=10
        ) as response:
            payload: object = json.load(response)
    except OSError:
        return None
    if not isinstance(payload, dict):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    key = first.get("key")
    return key if isinstance(key, str) else None


def main(argv: list[str] | None = None) -> int:
    """Audit every route at each width; return 1 when anything overflows."""
    parser = argparse.ArgumentParser(prog="tools/audit_layout.py")
    parser.add_argument("--url", default="http://localhost:8765")
    parser.add_argument("--widths", default="390,768,1280")
    parser.add_argument("--wait-ms", type=int, default=900)
    args = parser.parse_args(argv)

    base = args.url.rstrip("/")
    widths = [int(part) for part in args.widths.split(",") if part.strip()]
    key = _first_item_key(base)
    detail = f"/deviations-z02/{urllib.parse.quote(key)}" if key else None

    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in widths:
                page = browser.new_page(viewport={"width": width, "height": 900})
                for route in ("/", "/deviations-z02", "/jobs"):
                    page.goto(base + route, wait_until="networkidle", timeout=60_000)
                    page.wait_for_timeout(args.wait_ms)
                    viewport, scroll_width, offenders = _report(page)
                    label = f"{route} {width}px"
                    if scroll_width > viewport:
                        failures += 1
                        print(f"FAIL {label}: scrollWidth {scroll_width} > {viewport}")
                        for offender in offenders:
                            print(f"     {offender}")
                    else:
                        print(f"ok   {label}")

                # The list view shares the route but changes the layout.
                page.goto(base + "/deviations-z02", wait_until="networkidle")
                page.wait_for_timeout(args.wait_ms)
                page.get_by_role("button", name="List").click()
                page.wait_for_timeout(args.wait_ms)
                viewport, scroll_width, offenders = _report(page)
                label = f"/deviations-z02 (list) {width}px"
                if scroll_width > viewport:
                    failures += 1
                    print(f"FAIL {label}: scrollWidth {scroll_width} > {viewport}")
                    for offender in offenders:
                        print(f"     {offender}")
                else:
                    print(f"ok   {label}")

                if detail is not None:
                    page.goto(base + detail, wait_until="networkidle")
                    page.wait_for_timeout(args.wait_ms)
                    viewport, scroll_width, offenders = _report(page)
                    label = f"item detail {width}px"
                    if scroll_width > viewport:
                        failures += 1
                        print(f"FAIL {label}: scrollWidth {scroll_width} > {viewport}")
                        for offender in offenders:
                            print(f"     {offender}")
                    else:
                        print(f"ok   {label}")
                page.close()
        finally:
            browser.close()

    print(f"\n{failures} overflow(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
