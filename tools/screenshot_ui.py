"""Screenshot the UI state harness at the three review widths.

    npm --prefix frontend run dev -- --port 5173 &
    .venv/bin/python tools/screenshot_ui.py --url http://localhost:5173/dev/states

Writes ``docs/screenshots/<slug>-<width>.png`` for each width (default 390/768/1280).
Dev-only; not shipped in the wheel.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/screenshot_ui.py")
    parser.add_argument("--url", default="http://localhost:5173/dev/states")
    parser.add_argument("--slug", default="slice-a")
    parser.add_argument("--widths", default="390,768,1280")
    parser.add_argument("--wait-ms", type=int, default=1500)
    args = parser.parse_args(argv)

    widths = [int(part) for part in args.widths.split(",") if part.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in widths:
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(args.url, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(args.wait_ms)
                path = OUT_DIR / f"{args.slug}-{width}.png"
                page.screenshot(path=str(path), full_page=True)
                print(f"wrote {path}")
                page.close()
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
