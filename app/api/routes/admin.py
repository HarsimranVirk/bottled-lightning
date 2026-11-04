"""Admin endpoints: sessions, sync, jobs, workers and updates."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app import updater
from app.api.schemas import (
    ConcurrencyIn,
    JobLogsView,
    JobView,
    QueueView,
    SessionView,
    SyncView,
    UpdateStatusView,
)
from app.api.services import AdminPort
from app.types import JsonValue


def _text(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _update_view(payload: dict[str, JsonValue]) -> UpdateStatusView:
    """Project updater's loose payload onto the documented DTO."""
    available = payload.get("update_available")
    return UpdateStatusView(
        status=_text(payload, "status") or "unknown",
        update_available=bool(available),
        detail=_text(payload, "detail"),
        error=_text(payload, "error"),
        latest=_text(payload, "latest"),
        download_url=_text(payload, "download_url"),
    )


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
        """Ask the watcher to refresh immediately instead of waiting for the cycle."""
        admin.request_sync(workflow)
        return {"status": "requested", "workflow": workflow}

    @router.get("/jobs", response_model=list[JobView])
    def list_jobs(
        workflow: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[JobView]:
        """Jobs newest first, optionally filtered by workflow, kind and status."""
        return admin.jobs(workflow, kind, status, limit)

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

    @router.get("/updates", response_model=UpdateStatusView)
    def update_status() -> UpdateStatusView:
        """Last update-check result."""
        return _update_view(updater.status())

    @router.post("/updates/checks", response_model=UpdateStatusView)
    def update_checks() -> UpdateStatusView:
        """Run an update check now and return its result."""
        return _update_view(updater.check_for_update(force=True))

    @router.post("/updates/installations", status_code=202, response_model=UpdateStatusView)
    def install_update() -> UpdateStatusView:
        """Apply a pending update (the updater owns install safety)."""
        updater.apply_pending()
        return _update_view(updater.status())

    return router
