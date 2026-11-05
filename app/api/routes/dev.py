"""Dev-only DB explorer endpoints: table list, read-only query, export and purges."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response

from app.api.errors import ApiError
from app.api.schemas import (
    DevExportIn,
    DevQueryIn,
    DevQueryView,
    DevTablesView,
    DevTableView,
    PurgeIn,
    PurgeView,
)
from app.devtools.db import DevDbService, DevQueryError
from app.maintenance import PurgeError, PurgeScope, PurgeService


def _require(dev: DevDbService, request: Request) -> None:
    """Enforce the dev/localhost policy, hiding the surface with a 404."""
    host = request.client.host if request.client is not None else None
    try:
        dev.require_allowed(host)
    except DevQueryError as exc:
        raise ApiError(404, str(exc), "dev_tools_disabled") from exc


def make_dev_router(
    dev: DevDbService, purges: PurgeService | None = None
) -> APIRouter:
    """Build the dev database explorer under ``/dev/db``."""
    router = APIRouter(prefix="/dev/db", tags=["dev"])

    @router.get("/tables", response_model=DevTablesView)
    def tables(request: Request) -> DevTablesView:
        """Tables the explorer may query; ``sessions`` is never listed."""
        _require(dev, request)
        return DevTablesView(
            tables=[
                DevTableView(
                    name=table.name,
                    rows=table.rows,
                    columns=list(table.columns),
                )
                for table in dev.tables()
            ]
        )

    @router.post("/queries", response_model=DevQueryView)
    def query(request: Request, body: DevQueryIn) -> DevQueryView:
        """Run one read-only statement and return a bounded preview."""
        _require(dev, request)
        try:
            result = dev.query(body.sql, body.limit)
        except DevQueryError as exc:
            raise ApiError(422, str(exc), "dev_query_failed") from exc
        return DevQueryView(
            columns=list(result.columns),
            rows=[list(row) for row in result.rows],
            row_count=len(result.rows),
            truncated=result.truncated,
            duration_ms=result.duration_ms,
        )

    @router.post("/exports")
    def export(request: Request, body: DevExportIn) -> Response:
        """Export the same read-only query as CSV or a real Excel workbook."""
        _require(dev, request)
        try:
            if body.format == "csv":
                content: str | bytes = dev.export_csv(body.sql)
                media = "text/csv"
                extension = "csv"
            else:
                content = dev.export_xlsx(body.sql)
                media = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                extension = "xlsx"
        except DevQueryError as exc:
            raise ApiError(422, str(exc), "dev_export_failed") from exc
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = f"bottled-lightning-export-{stamp}.{extension}"
        return Response(
            content=content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if purges is not None:

        @router.post("/purges", response_model=PurgeView)
        def purge(request: Request, body: PurgeIn) -> PurgeView:
            """Run one manual retention scope; ``dryRun`` only reports counts."""
            _require(dev, request)
            try:
                result = purges.purge(
                    PurgeScope(body.scope),
                    dry_run=body.dry_run,
                )
            except PurgeError as exc:
                raise ApiError(409, str(exc), "purge_failed") from exc
            return PurgeView(
                scope=result.scope.value,
                cutoff=result.cutoff,
                dry_run=result.dry_run,
                deleted=result.deleted,
                total=result.total,
            )

    return router
