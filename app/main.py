"""FastAPI app + static frontend serving."""
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, store
from .routes import router

WEB_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(title="bottled-lightning", version="0.2.0")
app.include_router(router)


@app.on_event("startup")
def _startup():
    preexisting = config.DB_PATH.exists()
    store.init_db()
    print(f"* db ready: {config.DB_PATH}"
          f" ({'existing' if preexisting else 'created and initialized'})")


@app.get("/")
def index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"app": "bottled-lightning",
            "hint": "build the frontend: cd frontend && npm run build"}


# Serve the built SPA + assets. Registered after the API routes, so /api/*
# keeps precedence; html=True makes "/" serve index.html.
app.mount("/", StaticFiles(directory=str(WEB_DIR), check_dir=False, html=True),
          name="web")


def _lan_ip() -> Optional[str]:
    """Best-effort LAN address, so other devices know what to visit."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # no packets sent; just picks a route
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


if __name__ == "__main__":
    fresh = not config.DB_PATH.exists()
    store.init_db()
    ip = _lan_ip()
    print(f"* db: {config.DB_PATH} ({'created & initialized' if fresh else 'existing'})", flush=True)
    print("* frontend bundle:"
          f" {'built' if (WEB_DIR / 'index.html').exists() else 'NOT built (cd frontend && npm run build)'}",
          flush=True)
    print("* listening:", flush=True)
    print(f"    http://localhost:{config.PORT}", flush=True)
    if ip:
        print(f"    http://{ip}:{config.PORT}   <- visit from a device"
              " on the same network", flush=True)
    else:
        print("    (LAN IP not detected — use your machine's IP manually)",
              flush=True)
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT,
                log_level="info")
