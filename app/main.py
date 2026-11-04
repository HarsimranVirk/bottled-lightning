"""Application wiring: browser runtime, queue, watchers, API and static frontend.

``python -m app.main`` builds the whole stack, starts the browser loop and serves the
API + SPA. Tests build the API with :func:`app.api.create_app`, which needs no browser.
"""

from __future__ import annotations

import argparse
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config, updater
from .api import create_app
from .api.services import AdminService, WorkItemService
from .config import Settings, load_settings
from .core.registry import WorkflowRegistry
from .core.repo.attributes import AttributeRepository
from .core.repo.decisions import DecisionRepository
from .core.repo.edits import EditRepository
from .core.repo.events import EventRepository
from .core.repo.fields import FieldValueRepository
from .core.repo.jobs import JobRepository
from .core.repo.refs import PageRefRepository
from .core.repo.sessions import SessionRepository
from .core.repo.sync_runs import SyncRunRepository
from .core.repo.work_items import WorkItemRepository
from .core.workflow import WorkflowDeps
from .db.connection import Database
from .jobs.auth import AuthGate
from .jobs.dispatcher import Dispatcher
from .jobs.worker import Worker
from .pipeline.closure import ClosureResolver
from .pipeline.reconciler import Reconciler
from .pipeline.watcher import ListWatcher, WorkflowListSource
from .salesforce.runtime import BrowserRuntime
from .salesforce.session import SessionProvider
from .workflows.deviations_z02 import build_workflow
from .workflows.deviations_z02.adapters import build_adapters

PACKAGED_WEB_DIR = Path(__file__).resolve().parent / "web"
DEV_WEB_DIR = config.BASE_DIR / "frontend" / "dist"


def _web_dir() -> Path | None:
    """The SPA directory to serve, if a build exists.

    The wheel-packaged copy wins (that is what an installed build uses); a source
    checkout falls back to ``frontend/dist`` so ``npm run build`` is enough to see the UI.
    """
    for candidate in (PACKAGED_WEB_DIR, DEV_WEB_DIR):
        if (candidate / "index.html").exists():
            return candidate
    return None


def _lan_ip() -> str:
    """Best-effort LAN address for the boot banner."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host, _port = sock.getsockname()
            return host if isinstance(host, str) else "127.0.0.1"
    except OSError:
        return "127.0.0.1"


class Stack:
    """Everything the process owns, so shutdown can close it in one place."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings.db_path)
        self.database.migrate()

        self.items = WorkItemRepository(self.database)
        self.fields = FieldValueRepository(self.database)
        self.attributes = AttributeRepository(self.database)
        self.refs = PageRefRepository(self.database)
        self.edits = EditRepository(self.database)
        self.events = EventRepository(self.database)
        self.decisions = DecisionRepository(self.database)
        self.jobs = JobRepository(self.database)
        self.sessions_repo = SessionRepository(self.database)
        self.sync_runs = SyncRunRepository(self.database)

        self.provider = SessionProvider(self.sessions_repo, settings)
        self.auth = AuthGate(self.jobs, self.events)
        self.runtime = BrowserRuntime(settings, self.provider)

        self.registry = WorkflowRegistry()
        adapters = build_adapters(settings.org_base, settings.request_timeout_ms)
        self.workflow = build_workflow(
            settings,
            WorkflowDeps(
                items=self.items,
                fields=self.fields,
                attributes=self.attributes,
                refs=self.refs,
                events=self.events,
            ),
            adapters,
        )
        self.registry.register(self.workflow)

        self.closure = ClosureResolver(self.items, self.jobs, self.events)
        self.reconciler = Reconciler(
            self.workflow,
            self.items,
            self.jobs,
            self.attributes,
            self.sync_runs,
            self.closure,
        )
        source = WorkflowListSource(self.runtime, self.workflow, settings, self.provider)
        self.watchers: dict[str, ListWatcher] = {
            self.workflow.name: ListWatcher(
                self.workflow,
                source,
                self.reconciler,
                self.events,
                self.auth,
                settings.refresh_interval_s,
            )
        }

        self.worker = Worker(
            "w0",
            self.registry,
            self.items,
            self.jobs,
            self.events,
            self.auth,
            self.runtime,
            self.closure,
        )
        self.dispatcher = Dispatcher(self.jobs, self.worker, self.auth, settings)

        self.items_service = WorkItemService(
            self.registry,
            self.items,
            self.fields,
            self.attributes,
            self.refs,
            self.edits,
            self.decisions,
            self.jobs,
            self.events,
            lambda: self.auth.paused,
        )
        self.admin = AdminService(
            settings,
            self.runtime,
            self.provider,
            self.sessions_repo,
            self.sync_runs,
            self.jobs,
            self.auth,
            self.dispatcher,
            self.watchers,
            self.registry,
        )

    def start(self) -> None:
        """Start the browser loop, dispatcher and every watcher."""
        self.runtime.start()
        self.runtime.spawn(self.dispatcher.run_forever)
        for watcher in self.watchers.values():
            self.runtime.spawn(watcher.run_forever)

    def stop(self) -> None:
        """Stop the browser loop (watchers and dispatcher run on it) and close the DB."""
        self.runtime.stop()
        self.database.close()

    def app(self) -> FastAPI:
        """Build the HTTP app around this stack."""
        app = create_app(self.registry, self.items_service, self.admin)
        web = _web_dir()
        if web is None:

            @app.get("/", response_class=HTMLResponse)
            def index() -> str:
                """Placeholder page when the SPA has not been built."""
                return (
                    "<h2>bottled-lightning</h2>"
                    "<p>API is running. Build the frontend with "
                    "<code>npm --prefix frontend run build</code>.</p>"
                )

            return app

        root = web.resolve()
        assets = root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{path:path}", response_class=FileResponse)
        def spa(path: str) -> FileResponse:
            """Serve the SPA for client-side routes; real files win over index.html."""
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (root / path).resolve() if path else root
            if path and root in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

        return app


def main() -> None:
    """CLI entry point."""
    from .core.logging import configure_logging

    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bottled-lightning", description="Salesforce Lightning extraction webapp"
    )
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument(
        "--no-update", action="store_true", help="skip the GitHub update check"
    )
    args = parser.parse_args()
    if args.no_update:
        config.UPDATE_AUTO_START = False

    settings = load_settings()
    stack = Stack(settings)
    stack.start()
    updater.start_auto_update()
    print(
        f"* bottled-lightning {__version__} | data: {settings.data_dir} "
        f"| workers: {settings.workers}",
        flush=True,
    )
    print(
        f"* http://{_lan_ip()}:{args.port}  (local: http://127.0.0.1:{args.port})",
        flush=True,
    )
    try:
        uvicorn.run(stack.app(), host=args.host, port=args.port, log_level="info")
    finally:
        stack.stop()


if __name__ == "__main__":
    main()
