"""Item endpoints, generated once per registered workflow."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.schemas import (
    FieldValuesBody,
    ItemDetailView,
    ItemsPageView,
    JobView,
)
from app.api.services import WorkItemService
from app.core.workflow import Workflow


def make_router(workflow: Workflow, service: WorkItemService) -> APIRouter:
    """Build the REST surface for one workflow under its route (``/api/deviations``)."""
    router = APIRouter(prefix=f"/{workflow.route}", tags=[workflow.route])

    @router.get("", response_model=ItemsPageView)
    def list_items(
        status: str | None = None,
        q: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> ItemsPageView:
        """Unified view: one row per item with its editable values."""
        return service.list_items(workflow.name, status, q, limit, offset)

    @router.get("/{key}", response_model=ItemDetailView)
    def get_item(key: str) -> ItemDetailView:
        """One item with attributes, object links and edit history."""
        return service.get_item(workflow.name, key)

    @router.patch("/{key}/field-values", response_model=ItemDetailView)
    def patch_field_values(key: str, body: FieldValuesBody) -> ItemDetailView:
        """Propose editable values; ``null`` discards a proposal."""
        return service.patch_fields(workflow.name, key, body.root)

    @router.delete("/{key}/field-values", response_model=ItemDetailView)
    def discard_field_values(key: str) -> ItemDetailView:
        """Discard every proposal and return the item to ``ready``."""
        return service.discard_fields(workflow.name, key)

    @router.post("/{key}/jobs", status_code=202, response_model=JobView)
    def submit_item(key: str) -> JobView:
        """Enqueue the single ``SUBMIT`` job for this item."""
        return service.submit(workflow.name, key)

    return router
