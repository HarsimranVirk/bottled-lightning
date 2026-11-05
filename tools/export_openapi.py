"""Write the OpenAPI schema snapshot consumed by the frontend type generator.

    .venv/bin/python tools/export_openapi.py

Produces ``frontend/openapi.json``; ``npm --prefix frontend run types`` then regenerates
``frontend/src/types.ts``. Run this whenever an API payload changes — the committed
snapshot is what keeps the frontend from drifting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings
from app.main import Stack

OUTPUT = Path(__file__).resolve().parent.parent / "frontend" / "openapi.json"


def main() -> int:
    settings = load_settings()
    stack = Stack(settings)
    try:
        schema = stack.app().openapi()
    finally:
        stack.database.close()
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
