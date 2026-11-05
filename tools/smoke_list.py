"""Dev-only smoke check for the async browser layer. Not shipped in the wheel.

    .venv/bin/python tools/smoke_list.py

Requires a saved snapshot (``python -m app.salesforce.login``). Prints the header total,
the row count, whether the sample is valid, and the first few rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings
from app.core.errors import SessionExpired
from app.core.list_view import ListSample, ListViewSpec
from app.core.repo.sessions import SessionRepository
from app.db.connection import Database
from app.salesforce.list_page import ListPage
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider
from app.salesforce.urls import list_view_url
from app.workflows.deviations_z02 import LIST_FILTER, LIST_OBJECT_API, LIST_PATTERN


def main() -> int:
    settings = load_settings()
    database = Database(settings.db_path)
    database.migrate()
    session = SessionProvider(SessionRepository(database), settings)
    snapshot = session.snapshot
    if snapshot is None:
        print("no saved session — run: python -m app.salesforce.login", file=sys.stderr)
        return 2
    print(f"snapshot: {snapshot.cookie_count} cookies")

    runtime = BrowserRuntime(settings, session)
    runtime.start()
    try:

        async def work() -> ListSample:
            context = runtime.context
            page = await context.new_page()
            await session.ensure(page)
            list_page = ListPage(
                context,
                page,
                ListViewSpec(
                    url=list_view_url(
                        settings.org_base, LIST_OBJECT_API, LIST_FILTER
                    ),
                    pattern=LIST_PATTERN,
                ),
                settings.request_timeout_ms,
            )
            try:
                await list_page.open()
                return await list_page.read()
            finally:
                await list_page.close()

        sample = runtime.run(work)
        print(
            f"header={sample.header_total} rows={len(sample.rows)} "
            f"valid={sample.valid}"
        )
        for row in sample.rows[:5]:
            print(f"  {row.key}  approved={row.approved_at}  href={row.href[:70]}")
    except SessionExpired as exc:
        print(f"!! session expired: {exc}", file=sys.stderr)
        print("   run: python -m app.salesforce.login", file=sys.stderr)
        return 3
    finally:
        runtime.stop()
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
