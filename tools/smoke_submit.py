"""Dev-only: apply + validate one deviation against the live org.

    .venv/bin/python tools/smoke_submit.py --dry-run
    .venv/bin/python tools/smoke_submit.py Deviation-03112026-486382 \
        --loan-amount 14,50,000 --emi 18,585

The final Implement action is always disabled in this tool (``final_action=False``).
A successful run writes the proposed values, reads them back, and returns ``validated``.
Requires an extracted item with page refs; run ``tools/smoke_extract.py`` first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, load_settings
from app.core.errors import SessionExpired
from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.workflow import WorkflowDeps
from app.db.connection import Database
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider
from app.workflows.deviations_z02 import WORKFLOW_NAME
from app.workflows.deviations_z02.adapters import build_adapters
from app.workflows.deviations_z02.catalog import FIELD_CATALOG
from app.workflows.deviations_z02.submission import DeviationsZ02Submission


def _print_fields(deps: WorkflowDeps, key: str) -> None:
    """Print the stored field values for one item."""
    for field_key, field in sorted(deps.fields.for_item(WORKFLOW_NAME, key).items()):
        print(
            f"  field {field_key}: extracted={field.extracted} "
            f"synced={field.last_synced} proposed={field.proposed} "
            f"applied={field.applied} status={field.status.value}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/smoke_submit.py")
    parser.add_argument("key", nargs="?", help="deviation number (default: first ready item)")
    parser.add_argument("--loan-amount")
    parser.add_argument("--property-value")
    parser.add_argument("--tenure")
    parser.add_argument("--emi")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read the live values and selectors without writing anything",
    )
    args = parser.parse_args(argv)

    settings: Settings = load_settings()
    print(f"data dir: {settings.data_dir}")
    database = Database(settings.db_path)
    database.migrate()
    session = SessionProvider(SessionRepository(database), settings)
    if session.snapshot is None:
        print(
            "no saved session in this data dir — run: python -m app.salesforce.login",
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
    pipeline = DeviationsZ02Submission(
        WORKFLOW_NAME,
        deps.items,
        deps.fields,
        deps.refs,
        deps.events,
        adapters,
        FIELD_CATALOG,
        final_action=False,
    )

    if args.key is not None:
        item = deps.items.get(WORKFLOW_NAME, args.key)
    else:
        rows, _total = deps.items.list(WORKFLOW_NAME, None, None, 1, 0)
        item = rows[0] if rows else None
    if item is None:
        print(
            f"item not found: {args.key or '(no ready item)'} — run tools/smoke_extract.py first",
            file=sys.stderr,
        )
        database.close()
        return 4

    changes = {
        key: value
        for key, value in (
            ("loan_amount", args.loan_amount),
            ("property_value", args.property_value),
            ("tenure", args.tenure),
            ("emi_incl_hffc", args.emi),
        )
        if value is not None
    }
    if changes:
        deps.fields.propose(WORKFLOW_NAME, item.key, changes)
        print(f"proposed: {changes}")
    print(f"item: {item.key} status={item.status.value}")
    _print_fields(deps, item.key)

    runtime = BrowserRuntime(settings, session)
    runtime.start()
    try:

        async def work() -> str:
            tabs = runtime.new_tab_group()
            try:
                if args.dry_run:
                    preview = await pipeline.preview(
                        item, tabs, lambda message: print(f"  {message}", flush=True)
                    )
                    print("\nlive values (dry run):")
                    for kind, values in preview.items():
                        print(f"  {kind}:")
                        for label, value in values.items():
                            print(f"    {label}: {value!r}")
                    return "dry_run"
                return str(
                    await pipeline.run(
                        item, tabs, lambda message: print(f"  {message}", flush=True)
                    )
                )
            finally:
                await tabs.close_all()

        outcome = runtime.run(work)
        fresh = deps.items.require(WORKFLOW_NAME, item.key)
        print(f"\noutcome: {outcome}")
        print(f"item: {fresh.key} status={fresh.status.value} reason={fresh.reason}")
        _print_fields(deps, item.key)
        return 0 if outcome in {"dry_run", "validated", "already_closed"} else 1
    except SessionExpired as exc:
        print(f"!! session expired: {exc}", file=sys.stderr)
        print("   run: python -m app.salesforce.login", file=sys.stderr)
        return 3
    finally:
        runtime.stop()
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
