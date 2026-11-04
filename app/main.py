"""FastAPI app + static frontend serving."""

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config, store, sync, updater
from .jobs import shutdown_pool
from .routes import router

PACKAGED_WEB_DIR = Path(__file__).resolve().parent / "web"
DEV_WEB_DIR = config.BASE_DIR / "frontend" / "dist"
WEB_DIR = PACKAGED_WEB_DIR if (PACKAGED_WEB_DIR / "index.html").exists() else DEV_WEB_DIR


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    preexisting = config.DB_PATH.exists()
    store.init_db()
    stale = store.fail_stale_running_jobs()
    if stale:
        print(f"* marked {stale} stale running job(s) as failed")
    print(
        f"* db ready: {config.DB_PATH} ({'existing' if preexisting else 'created and initialized'})"
    )
    print(
        f"* bottled-lightning v{__version__}"
        f" | data: {config.DATA_DIR}"
        f" | update policy: {config.UPDATE_POLICY}"
    )
    from .jobs import _start_pool

    _start_pool(config.SCRAPE_WORKERS)
    print(f"* worker pool started: {config.SCRAPE_WORKERS} always-alive sessions")
    if config.RESYNC_AUTO_START:
        sync.start()
        print(
            f"* resync loop started: list view visited every "
            f"{config.RESYNC_INTERVAL_SECONDS}s"
        )
    updater.start_auto_update()
    yield
    sync.stop()
    shutdown_pool()
    print("* worker pool stopped")


app = FastAPI(title="bottled-lightning", version=__version__, lifespan=lifespan)
app.include_router(router)


@app.get("/", response_model=None)
def index() -> FileResponse | dict[str, str]:
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"app": "bottled-lightning", "hint": "build the frontend: cd frontend && npm run build"}


app.mount("/", StaticFiles(directory=str(WEB_DIR), check_dir=False, html=True), name="web")


def _lan_ip() -> str | None:
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        return None


def main() -> None:
    from .core.logging import configure_logging

    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bottled-lightning", description="Salesforce Lightning extraction webapp"
    )
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument(
        "--no-update", action="store_true", help="skip the GitHub update check for this run"
    )
    args = parser.parse_args()
    if args.no_update:
        config.UPDATE_AUTO_START = False

    fresh = not config.DB_PATH.exists()
    store.init_db()
    store.fail_stale_running_jobs()
    ip = _lan_ip()
    print(f"* bottled-lightning v{__version__}", flush=True)
    print(
        f"* db: {config.DB_PATH} ({'created & initialized' if fresh else 'existing'})", flush=True
    )
    print(
        f"* frontend bundle: {'built' if (WEB_DIR / 'index.html').exists() else 'NOT built'}",
        flush=True,
    )
    print("* listening:", flush=True)
    print(f"    http://localhost:{args.port}", flush=True)
    if ip:
        print(
            f"    http://{ip}:{args.port}   <- visit from a device on the same network", flush=True
        )
    else:
        print("    (LAN IP not detected — use your machine's IP manually)", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
