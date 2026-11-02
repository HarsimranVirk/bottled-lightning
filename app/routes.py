"""REST endpoints."""
import csv
import io
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import jobs, store

router = APIRouter(prefix="/api")


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=10)
    pattern: str = Field(default=r"Deviation-\d+-\d+", max_length=120)


@router.get("/views")
def get_views():
    return store.list_views()


@router.post("/views", status_code=201)
def post_view(body: ViewIn):
    if "lightning.force.com/lightning/o/" not in body.url:
        raise HTTPException(400, "URL must be a Lightning list view URL")
    return store.add_view(body.name, body.url, body.pattern)


@router.delete("/views/{view_id}")
def del_view(view_id: int):
    if not store.delete_view(view_id):
        raise HTTPException(404, "view not found")
    return {"deleted": view_id}


@router.post("/views/{view_id}/run", status_code=202)
def run_view(view_id: int):
    view = store.get_view(view_id)
    if not view:
        raise HTTPException(404, "view not found")
    job_id = store.create_job(view_id)
    jobs.run_job_async(view_id, job_id)
    return {"job_id": job_id, "view_id": view_id}


@router.get("/jobs")
def get_jobs():
    return store.list_jobs()


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.get("/views/{view_id}/results")
def get_results(view_id: int):
    if not store.get_view(view_id):
        raise HTTPException(404, "view not found")
    return {"view": store.get_view(view_id)["name"], "rows": store.latest_values(view_id)}


@router.get("/views/{view_id}/results.csv")
def get_results_csv(view_id: int):
    if not store.get_view(view_id):
        raise HTTPException(404, "view not found")
    rows = store.latest_values(view_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["DeviationNo", "FirstSeen", "LastSeen"])
    for r in rows:
        w.writerow([r["value"], r["first_seen"], r["last_seen"]])
    buf.seek(0)
    filename = f"view{view_id}_deviations.csv"
    return StreamingResponse(buf, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/session")
def session_status():
    """Cheap check the UI can call to prompt for re-login."""
    from . import config
    return {"auth_snapshot_exists": config.AUTH_FILE.exists()}
