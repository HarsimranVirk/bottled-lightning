"""Dev-only: apply + validate one deviation against the live org.

    .venv/bin/python tools/smoke_submit.py --dry-run
    .venv/bin/python tools/smoke_submit.py --no-op Deviation-03112026-486382
    .venv/bin/python tools/smoke_submit.py Deviation-03112026-486382 \
        --loan-amount 14,50,000 --emi 18,585

The final Implement action is always disabled in this tool (``final_action=False``).
A successful run writes the proposed values, reads them back, and returns ``validated``.
``--no-op`` bypasses proposals entirely: every page is read, the same values are written
back, and the pages are read again. Requires an extracted item with page refs; run
``tools/smoke_extract.py`` first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, load_settings
from app.core.errors import SessionExpired
from app.core.field import EditableField, FieldTarget, ValueType, normalise
from app.core.models import WorkItem
from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import WriteOutcome
from app.core.workflow import WorkflowDeps
from app.db.connection import Database
from app.salesforce.adapters import AdapterRegistry
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider
from app.salesforce.tabs import TabSessions
from app.workflows.deviations_z02 import WORKFLOW_NAME
from app.workflows.deviations_z02.adapters import build_adapters
from app.workflows.deviations_z02.catalog import FIELD_CATALOG, DeviationObject
from app.workflows.deviations_z02.submission import DeviationsZ02Submission


def _print_fields(deps: WorkflowDeps, key: str) -> None:
    """Print the stored field values for one item."""
    for field_key, field in sorted(deps.fields.for_item(WORKFLOW_NAME, key).items()):
        print(
            f"  field {field_key}: extracted={field.extracted} "
            f"synced={field.last_synced} proposed={field.proposed} "
            f"applied={field.applied} status={field.status.value}"
        )


def _canonical(value: str | None, spec: EditableField) -> str | None:
    """Normalise one read value for comparison, or leave it raw when unparseable."""
    if value is None:
        return None
    try:
        return normalise(value, spec.value_type)
    except ValueError:
        return value.strip()


def _plausible_amount(canonical: str) -> bool:
    """Reject obviously malformed/concatenated amounts before a no-op write."""
    digits = canonical.split(".", 1)[0].lstrip("-")
    return digits.isdigit() and len(digits) <= 12


async def _run_noop(
    item: WorkItem,
    deps: WorkflowDeps,
    adapters: AdapterRegistry,
    tabs: TabSessions,
) -> bool:
    """
    Read every target, write the same value back, and read it again.

    This is the adapter-level no-op check: it never looks at the description, never
    creates a proposal and never changes the item status. It proves the page edit
    mechanics against the values Salesforce currently holds. A target that cannot be
    read is reported as a failure; nothing is guessed or filled in.
    """
    refs = deps.refs.for_item(WORKFLOW_NAME, item.key)
    target_spec: dict[FieldTarget, EditableField] = {
        target: spec for spec in FIELD_CATALOG for target in spec.targets
    }
    kinds: list[str] = []
    for spec in FIELD_CATALOG:
        for target in spec.targets:
            if target.object_kind not in kinds:
                kinds.append(target.object_kind)

    ok = True
    for kind in kinds:
        targets = [
            target
            for spec in FIELD_CATALOG
            for target in spec.targets
            if target.object_kind == kind
        ]
        ref = refs.get(kind)
        if ref is None:
            print(f"\n{kind}: no page link; skipped")
            ok = False
            continue

        adapter = adapters.get(kind)
        page = await adapter.open(tabs, ref)
        try:
            current = await adapter.read(page, targets)
            print(f"\n{kind}:")
            values: dict[FieldTarget, str] = {}
            for target in targets:
                spec = target_spec[target]
                raw = current.get(target)
                canonical = _canonical(raw, spec)
                print(
                    f"  {target.label} [{target.section or ''}]: "
                    f"current={raw!r} canonical={canonical!r}"
                )
                if canonical is None:
                    continue
                if (
                    spec.value_type is ValueType.AMOUNT
                    and not _plausible_amount(canonical)
                ):
                    print("  implausible amount; write skipped")
                    ok = False
                    continue
                values[target] = canonical

            if not values:
                print("  no readable values; write skipped")
                ok = False
                continue

            if kind == DeviationObject.LMS2_CL_CONTRACT.value:
                print(
                    "  no-op write skipped: Contract Modification rejects unchanged "
                    "values (it requires a real change)"
                )
                continue

            outcomes = await adapter.write(page, values)
            after = await adapter.read(page, targets)
            for target in targets:
                spec = target_spec[target]
                before = _canonical(current.get(target), spec)
                now = _canonical(after.get(target), spec)
                outcome = outcomes.get(target)
                good = (
                    before is not None
                    and now is not None
                    and before == now
                    and outcome is WriteOutcome.SAVED
                )
                if not good:
                    ok = False
                print(
                    f"  {target.label}: "
                    f"write={outcome.value if outcome is not None else 'not attempted'} "
                    f"before={before!r} after={now!r} "
                    f"{'OK' if good else 'FAIL'}"
                )
        finally:
            await tabs.close_page(page)
    return ok


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
    parser.add_argument(
        "--no-op",
        action="store_true",
        help="read each page, write the current values back, and read them again",
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

    if args.no_op:
        print(f"item: {item.key} — no-op adapter check")
        runtime = BrowserRuntime(settings, session)
        runtime.start()
        try:

            async def noop_work() -> bool:
                tabs = runtime.new_tab_group()
                try:
                    return await _run_noop(item, deps, adapters, tabs)
                finally:
                    await tabs.close_all()

            ok = runtime.run(noop_work)
            print(f"\nno-op result: {'PASS' if ok else 'FAIL'}")
            return 0 if ok else 1
        except SessionExpired as exc:
            print(f"!! session expired: {exc}", file=sys.stderr)
            print("   run: python -m app.salesforce.login", file=sys.stderr)
            return 3
        finally:
            runtime.stop()
            database.close()

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
