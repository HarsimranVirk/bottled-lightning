"""Item endpoints, generated once per registered workflow."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.errors import ApiError
from app.api.schemas import (
    DecisionBody,
    FieldValuesBody,
    ItemDetailView,
    ItemsPageView,
    JobView,
)
from app.api.services import WorkItemService
from app.core.repo.approved_history import HistoryQuery
from app.core.workflow import Workflow


def _pairs(values: list[str] | None, name: str) -> tuple[tuple[str, str], ...]:
    """Parse repeated ``key:value`` filter values, rejecting a missing separator."""
    pairs: list[tuple[str, str]] = []
    for raw in values or ():
        key, separator, value = raw.partition(":")
        if not separator or not key.strip():
            raise ApiError(
                422,
                f"{name} must be field_key:value",
                "invalid_history_filter",
            )
        pairs.append((key.strip(), value))
    return tuple(pairs)


def make_router(workflow: Workflow, service: WorkItemService) -> APIRouter:
    """Build the REST surface for one workflow under its route (``/api/deviations``)."""
    router = APIRouter(prefix=f"/{workflow.route}", tags=[workflow.route])

    @router.get("", response_model=ItemsPageView)
    def list_items(
        status: Annotated[list[str] | None, Query()] = None,
        decision: str | None = None,
        q: str | None = None,
        sort: str = "last_seen",
        order: str = "desc",
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> ItemsPageView:
        """Unified view: one row per item with its values and current decision.

        ``status`` is repeatable (``?status=ready&status=needs_review``); ``decision``
        is ``accept``, ``reject`` or ``undecided``.
        """
        return service.list_items(
            workflow.name, status, q, limit, offset, decision, sort, order
        )

    @router.get("/history", response_model=ItemsPageView)
    def list_history(
        q: str | None = None,
        key: str | None = None,
        key_in: Annotated[list[str] | None, Query()] = None,
        status_text: str | None = None,
        status: Annotated[list[str] | None, Query()] = None,
        approved_at: str | None = None,
        approved_at_in: Annotated[list[str] | None, Query()] = None,
        decided_after: str | None = None,
        decided_before: str | None = None,
        field: Annotated[list[str] | None, Query()] = None,
        field_text: Annotated[list[str] | None, Query()] = None,
        limit: int = Query(default=25, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> ItemsPageView:
        """Accepted-deviation snapshots with the standard server-side filter row.

        This is a separate read model from the live item list; it survives the current
        work-item purge.
        """
        return service.list_history(
            workflow.name,
            HistoryQuery(
                q=q,
                key=key,
                keys=tuple(value for value in key_in or () if value.strip()),
                status_text=status_text,
                statuses=tuple(value for value in status or () if value.strip()),
                approved_at=approved_at,
                approved_values=tuple(
                    value for value in approved_at_in or () if value.strip()
                ),
                decided_after=decided_after,
                decided_before=decided_before,
                field_text=_pairs(field_text, "field_text"),
                field_values=_pairs(field, "field"),
                limit=limit,
                offset=offset,
            ),
        )

    @router.get("/history/{key}", response_model=ItemDetailView)
    def get_history_item(key: str) -> ItemDetailView:
        """One approved snapshot with its attributes, refs, edits and accept decision."""
        return service.get_history_item(workflow.name, key)

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

    @router.post("/{key}/decisions", response_model=ItemDetailView)
    def decide(key: str, body: DecisionBody) -> ItemDetailView:
        """Record an accept/reject review decision (local, reversible)."""
        return service.decide(workflow.name, key, body.decision, body.reason)

    @router.delete("/{key}/decisions", response_model=ItemDetailView)
    def undo_decision(key: str) -> ItemDetailView:
        """Undo the current decision and return the item to the deck."""
        return service.undo_decision(workflow.name, key)

    @router.post("/{key}/jobs", status_code=202, response_model=JobView)
    def submit_item(key: str) -> JobView:
        """Enqueue the single ``SUBMIT`` job for this item."""
        return service.submit(workflow.name, key)

    return router
