"""FastAPI app + static frontend serving."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import store
from .routes import router

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Salesforce UI Automation", version="0.1.0")
app.include_router(router)


@app.on_event("startup")
def _startup():
    store.init_db()


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
