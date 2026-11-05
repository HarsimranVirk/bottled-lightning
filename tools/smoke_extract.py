"""Dev-only: extract one deviation against the live org. Not shipped in the wheel.

    .venv/bin/python tools/smoke_extract.py
    .venv/bin/python tools/smoke_extract.py Deviation-28102026-484106

Requires a saved session (``python -m app.salesforce.login`` in the same data directory).
Extraction only reads Salesforce; nothing is written back (that starts in Phase 6).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, load_settings
from app.core.errors import SessionExpired
from app.core.list_view import ListRow, ListSample, ListViewSpec
from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.workflow import WorkflowDeps
from app.db.connection import Database
from app.salesforce.list_page import ListPage
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider
from app.workflows.deviations_z02 import WORKFLOW_NAME
from app.workflows.deviations_z02.adapters import build_adapters
from app.workflows.deviations_z02.extraction import DeviationsZ02Extraction


def _pick(sample: ListSample, key: str | None) -> ListRow | None:
    if key is not None:
        return next((row for row in sample.rows if row.key == key), None)
    return sample.rows[0] if sample.rows else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/smoke_extract.py")
    parser.add_argument("key", nargs="?", help="deviation number (default: first row)")
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="respect extracted_at instead of re-extracting",
    )
    args = parser.parse_args(argv)

    settings: Settings = load_settings()
    print(f"data dir: {settings.data_dir}")
    database = Database(settings.db_path)
    database.migrate()
    session = SessionProvider(SessionRepository(database), settings)
    if session.snapshot is None:
        print(
            "no saved session in this data dir — run: "
            "python -m app.salesforce.login",
            file=sys.stderr,
        )
        database.close()
        return 2

    deps = WorkflowDeps(
        items=WorkItemRepository(database),
        fields=FieldValueRepository(database),
        attributes=AttributeRepository(database),
        refs=PageRefRepository(database),
        events=EventRepository(database),
    )
    adapters = build_adapters(settings.org_base, settings.request_timeout_ms)
    pipeline = DeviationsZ02Extraction(
        WORKFLOW_NAME,
        deps.items,
        deps.fields,
        deps.attributes,
        deps.refs,
        deps.events,
        adapters,
        force=not args.no_force,
    )

    runtime = BrowserRuntime(settings, session)
    runtime.start()
    try:

        async def work() -> tuple[str, str]:
            context = runtime.context
            page = await context.new_page()
            list_page = ListPage(
                context,
                page,
                ListViewSpec(
                    url=settings.deviations_z02_list_url,
                    pattern=settings.deviations_z02_pattern,
                ),
                settings.request_timeout_ms,
            )
            try:
                await session.ensure(page)
                await list_page.open()
                sample = await list_page.read()
                print(
                    f"list: header={sample.header_total} rows={len(sample.rows)} "
                    f"valid={sample.valid}"
                )
                row = _pick(sample, args.key)
                if row is None:
                    raise LookupError(
                        f"{args.key} not in the list view "
                        f"(saw {', '.join(r.key for r in sample.rows[:5])})"
                    )
                item = deps.items.create_present(
                    WORKFLOW_NAME, row, sample.captured_at
                )
                tabs = runtime.new_tab_group()
                try:
                    outcome = await pipeline.run(
                        item, tabs, lambda message: print(f"  {message}", flush=True)
                    )
                finally:
                    await tabs.close_all()
                return str(outcome), item.key
            finally:
                await list_page.close()

        outcome, key = runtime.run(work)
        item = deps.items.require(WORKFLOW_NAME, key)
        print(f"\noutcome: {outcome}")
        print(f"item: {item.key} status={item.status} reason={item.reason}")
        for field_key, field in sorted(deps.fields.for_item(WORKFLOW_NAME, key).items()):
            print(
                f"  field {field_key}: extracted={field.extracted} "
                f"synced={field.last_synced} proposed={field.proposed}"
            )
        for name, value in sorted(deps.attributes.for_item(WORKFLOW_NAME, key).items()):
            print(f"  attr  {name}: {value}")
        for kind, ref in sorted(deps.refs.for_item(WORKFLOW_NAME, key).items()):
            print(f"  ref   {kind}: {ref.name} → {ref.url}")
        return 0 if outcome == "extracted" else 1
    except SessionExpired as exc:
        print(f"!! session expired: {exc}", file=sys.stderr)
        print("   run: python -m app.salesforce.login", file=sys.stderr)
        return 3
    except LookupError as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 4
    finally:
        runtime.stop()
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
