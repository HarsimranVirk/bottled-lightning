"""FastAPI application factory for the workflow API."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.errors import ApiError
from app.api.routes import make_admin_router, make_dev_router, make_workflow_router
from app.api.schemas import WorkflowView
from app.api.services import AdminPort, WorkItemService
from app.core.registry import WorkflowRegistry
from app.devtools.db import DevDbService


def _api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Translate ``ApiError`` into the documented error body."""
    if isinstance(exc, ApiError):
        detail: dict[str, str] = {"message": exc.detail}
        if exc.code is not None:
            detail["code"] = exc.code
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})
    return JSONResponse(
        status_code=500, content={"detail": {"message": "internal error"}}
    )


def create_app(
    registry: WorkflowRegistry,
    items: WorkItemService,
    admin: AdminPort,
    devtools: DevDbService | None = None,
) -> FastAPI:
    """Build the API app: one workflow router per registered workflow plus admin.

    The app is transport only — startup of the browser runtime, dispatcher and watchers
    is the caller's job, which keeps this factory usable in tests without a browser.
    """
    app = FastAPI(title="bottled-lightning", version=__version__)
    app.add_exception_handler(ApiError, _api_error_handler)

    api_router = make_admin_router(admin)

    @api_router.get("/workflows", response_model=list[WorkflowView])
    def list_workflows() -> list[WorkflowView]:
        """Every registered workflow with its editable-field catalogue."""
        return items.list_workflows()

    for workflow in registry.all():
        api_router.include_router(make_workflow_router(workflow, items))
    if devtools is not None:
        api_router.include_router(make_dev_router(devtools))

    app.include_router(api_router, prefix="/api")
    return app
