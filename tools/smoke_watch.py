"""Dev-only: run one watcher cycle through the real list view. Not shipped in the wheel.

    .venv/bin/python tools/smoke_watch.py

Opens the dedicated list page, samples it, reconciles the store and prints the recorded
``sync_runs`` row plus what changed. Requires a saved session.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings
from app.core.errors import SessionExpired
from app.core.models import SyncRun
from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.jobs import JobQuery, JobRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.sync_runs import SyncRunRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import JobStatus
from app.core.workflow import WorkflowDeps
from app.db.connection import Database
from app.jobs.auth import AuthGate
from app.pipeline.closure import ClosureResolver
from app.pipeline.reconciler import Reconciler
from app.pipeline.watcher import ListWatcher, WorkflowListSource
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider
from app.workflows.deviations_z02 import build_workflow


def main() -> int:
    settings = load_settings()
    database = Database(settings.db_path)
    database.migrate()
    session = SessionProvider(SessionRepository(database), settings)
    if session.snapshot is None:
        print("no saved session — run: python -m app.salesforce.login", file=sys.stderr)
        database.close()
        return 2

    jobs = JobRepository(database)
    events = EventRepository(database)
    deps = WorkflowDeps(
        items=WorkItemRepository(database),
        fields=FieldValueRepository(database),
        attributes=AttributeRepository(database),
        refs=PageRefRepository(database),
        events=events,
    )
    workflow = build_workflow(settings, deps)
    closure = ClosureResolver(deps.items, jobs, events)
    reconciler = Reconciler(
        workflow,
        deps.items,
        jobs,
        deps.attributes,
        deps.refs,
        SyncRunRepository(database),
        closure,
    )
    auth = AuthGate(jobs, events)
    runtime = BrowserRuntime(settings, session)
    runtime.start()
    try:
        source = WorkflowListSource(runtime, workflow, settings, session)
        watcher = ListWatcher(
            workflow, source, reconciler, events, auth, settings.refresh_interval_s
        )

        async def work() -> SyncRun:
            try:
                return await watcher.refresh_once()
            finally:
                await source.close()

        run = runtime.run(work)
        print(
            f"sync {run.workflow}: captured={run.captured_at} "
            f"header={run.header_total} rows={run.rows_read} valid={run.valid}"
        )
        print(f"  warning={run.warning} added={run.added} updated={run.updated} "
              f"closed={run.closed}")
        items = deps.items.present(workflow.name)
        print(f"  present items: {len(items)}")
        for item in items[:5]:
            print(f"    {item.key} status={item.status} approved={item.approved_at}")
        queued = jobs.query(JobQuery(workflow=workflow.name, status=JobStatus.QUEUED))
        print(f"  queued jobs: {len(queued.jobs)}")
        return 0
    except SessionExpired as exc:
        print(f"!! session expired: {exc}", file=sys.stderr)
        return 3
    finally:
        runtime.stop()
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
