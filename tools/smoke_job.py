"""Dev-only: run one EXTRACT job through the real queue. Not shipped in the wheel.

    SF_DATA_DIR=./data-v2 .venv/bin/python tools/smoke_job.py
    SF_DATA_DIR=./data-v2 .venv/bin/python tools/smoke_job.py Deviation-03112026-486382

Exercises the same path the app will use: list row -> queued job -> dispatcher ->
worker -> extraction pipeline -> job logs. Requires a saved session.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings
from app.core.errors import SessionExpired
from app.core.list_view import ListRow, ListSample, ListViewSpec
from app.core.models import Job
from app.core.registry import WorkflowRegistry
from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.sessions import SessionRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import JobKind, JobStatus
from app.core.workflow import WorkflowDeps
from app.db.connection import Database
from app.jobs.auth import AuthGate
from app.jobs.dispatcher import Dispatcher
from app.jobs.worker import Worker
from app.salesforce.list_page import ListPage
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import SessionProvider
from app.workflows.deviations_z02 import WORKFLOW_NAME, build_workflow
from app.workflows.deviations_z02.adapters import build_adapters

TERMINAL = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


def _pick(sample: ListSample, key: str | None) -> ListRow | None:
    if key is not None:
        return next((row for row in sample.rows if row.key == key), None)
    return sample.rows[0] if sample.rows else None


async def _wait_done(jobs: JobRepository, job_id: int, timeout_s: float) -> Job:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        job = jobs.require(job_id)
        if job.status in TERMINAL:
            return job
        await asyncio.sleep(0.5)
    raise TimeoutError(f"job {job_id} did not finish in {timeout_s}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/smoke_job.py")
    parser.add_argument("key", nargs="?", help="deviation number (default: first row)")
    args = parser.parse_args(argv)

    settings = load_settings()
    database = Database(settings.db_path)
    database.migrate()
    session = SessionProvider(SessionRepository(database), settings)
    if session.snapshot is None:
        print("no saved session — run: python -m app.salesforce.login", file=sys.stderr)
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
    workflow = build_workflow(settings, deps, adapters, force=True)
    registry = WorkflowRegistry()
    registry.register(workflow)

    jobs = JobRepository(database)
    auth = AuthGate(jobs, deps.events)
    runtime = BrowserRuntime(settings, session)
    runtime.start()
    try:
        worker = Worker("smoke", registry, deps.items, jobs, deps.events, auth, runtime)
        dispatcher = Dispatcher(jobs, worker, auth, settings, poll_s=0.2)

        async def work() -> tuple[int, str]:
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
                print(f"list: header={sample.header_total} rows={len(sample.rows)}")
                row = _pick(sample, args.key)
                if row is None:
                    raise LookupError(f"{args.key} not on the list")
                deps.items.create_present(WORKFLOW_NAME, row, sample.captured_at)
            finally:
                await list_page.close()

            job = jobs.enqueue(WORKFLOW_NAME, JobKind.EXTRACT, row.key)
            print(f"queued job {job.id} for {row.key}")
            task = asyncio.create_task(dispatcher.run_forever())
            try:
                done = await _wait_done(jobs, job.id, timeout_s=600)
            finally:
                dispatcher.stop()
                await task
            return done.id, done.status.value

        job_id, status = runtime.run(work)
        print(f"\njob {job_id}: {status}")
        for line in jobs.logs(job_id):
            print(f"  {line}")
        job = jobs.require(job_id)
        print(f"error: {job.error}")
        return 0 if job.status is JobStatus.SUCCEEDED else 1
    except SessionExpired as exc:
        print(f"!! session expired: {exc}", file=sys.stderr)
        return 3
    except (LookupError, TimeoutError) as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 4
    finally:
        runtime.stop()
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
