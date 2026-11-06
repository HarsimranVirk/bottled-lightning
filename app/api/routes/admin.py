"""Admin endpoints: sessions, sync, jobs, workers and updates."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app import __version__, updater
from app.api.schemas import (
    ConcurrencyIn,
    JobLogsView,
    JobsPageView,
    NetworkView,
    QueueView,
    SessionView,
    SyncView,
    UpdateStatusView,
    VersionView,
)
from app.api.services import AdminPort, update_status_view


def make_router(admin: AdminPort) -> APIRouter:
    """Build the admin surface around one admin gateway."""
    router = APIRouter(tags=["admin"])

    @router.get("/sessions", response_model=SessionView)
    def get_session() -> SessionView:
        """Current auth state, whether dispatch is paused, and the last auth event."""
        return admin.session()

    @router.post("/sessions", status_code=202, response_model=SessionView)
    def start_login() -> SessionView:
        """Start a headed manual login; the snapshot is saved when the operator finishes."""
        return admin.login()

    @router.delete("/sessions", status_code=204)
    def clear_session() -> Response:
        """Forget the saved snapshot and pause dispatch until a new login."""
        admin.logout()
        return Response(status_code=204)

    @router.get("/syncs", response_model=SyncView | None)
    def get_sync(workflow: str) -> SyncView | None:
        """The latest recorded refresh for a workflow, or ``null`` before the first."""
        return admin.latest_sync(workflow)

    @router.post("/syncs", status_code=202)
    def request_sync(workflow: str) -> dict[str, str]:
        """Refresh now instead of waiting for the cycle; ``409`` when login is required."""
        admin.request_sync(workflow)
        return {"status": "requested", "workflow": workflow}

    @router.get("/jobs", response_model=JobsPageView)
    def list_jobs(
        workflow: str | None = None,
        kind: Annotated[list[str] | None, Query()] = None,
        status: Annotated[list[str] | None, Query()] = None,
        phase: Annotated[list[str] | None, Query()] = None,
        status_text: str | None = None,
        kind_text: str | None = None,
        phase_text: str | None = None,
        item: str | None = None,
        item_in: Annotated[list[str] | None, Query()] = None,
        job_id: Annotated[str | None, Query(alias="id")] = None,
        id_in: Annotated[list[str] | None, Query()] = None,
        error: str | None = None,
        error_in: Annotated[list[str] | None, Query()] = None,
        started_after: str | None = None,
        started_before: str | None = None,
        duration_min_ms: int | None = Query(default=None, ge=0),
        duration_max_ms: int | None = Query(default=None, ge=0),
        sort: str = "id",
        order: str = "desc",
        limit: int = Query(default=25, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> JobsPageView:
        """One filtered, sorted page of jobs (FR-7.10)."""
        return admin.jobs(
            workflow=workflow,
            kind=kind,
            status=status,
            phase=phase,
            status_text=status_text,
            kind_text=kind_text,
            phase_text=phase_text,
            item=item,
            item_in=item_in,
            job_id=job_id,
            id_in=id_in,
            error=error,
            error_in=error_in,
            started_after=started_after,
            started_before=started_before,
            duration_min_ms=duration_min_ms,
            duration_max_ms=duration_max_ms,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )

    @router.get("/jobs/{job_id}", response_model=JobLogsView)
    def get_job(job_id: int) -> JobLogsView:
        """One job with its log lines."""
        return admin.job_logs(job_id)

    @router.get("/jobs/{job_id}/logs", response_model=JobLogsView)
    def get_job_logs(job_id: int) -> JobLogsView:
        """Job detail and logs (kept as a sub-resource for the UI)."""
        return admin.job_logs(job_id)

    @router.delete("/jobs/{job_id}", status_code=204)
    def cancel_job(job_id: int) -> Response:
        """Cancel a queued job; running work is never interrupted mid-write."""
        admin.cancel_job(job_id)
        return Response(status_code=204)

    @router.get("/workers", response_model=QueueView)
    def get_workers() -> QueueView:
        """Concurrency, in-flight slots, pause state and job counts."""
        return admin.queue()

    @router.patch("/workers", response_model=QueueView)
    def set_workers(body: ConcurrencyIn) -> QueueView:
        """Change the worker count (1–5); shrinking lets running jobs finish."""
        return admin.set_concurrency(body.concurrency)

    @router.get("/version", response_model=VersionView)
    def get_version() -> VersionView:
        """The running app version; the footer shows it on every screen."""
        return VersionView(version=__version__)

    @router.get("/network", response_model=NetworkView)
    def get_network() -> NetworkView:
        """Bind host, port and the LAN address for the home page."""
        return admin.network()

    @router.get("/updates", response_model=UpdateStatusView)
    def update_status() -> UpdateStatusView:
        """Last update-check or install result."""
        return admin.update_status()

    @router.post("/updates/checks", response_model=UpdateStatusView)
    def update_checks() -> UpdateStatusView:
        """Run an update check now and return its result."""
        return update_status_view(updater.check_for_update(force=True))

    @router.post("/updates/installations", status_code=202, response_model=UpdateStatusView)
    def install_update() -> UpdateStatusView:
        """Install the pending update; ``409`` when it is not safe to restart now."""
        return admin.install_update()

    return router
