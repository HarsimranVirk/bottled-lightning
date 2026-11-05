"""Settings (org URLs, data dir, update policy; env-overridable)."""

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SF_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
ORG_BASE = os.environ.get("SF_ORG_BASE", "https://hffc.lightning.force.com")
REQUEST_TIMEOUT_MS = 60_000
LOGIN_WAIT_SECONDS = 600
HOST = os.environ.get("SF_HOST", "0.0.0.0")
PORT = int(os.environ.get("SF_PORT", "8765"))
IS_SOURCE_CHECKOUT = (BASE_DIR / "frontend" / "src").exists()
UPDATE_POLICY = os.environ.get("SF_UPDATE_POLICY", "auto")
UPDATE_AUTO_START = True
UPDATE_ALLOW_SOURCE = os.environ.get("SF_UPDATE_ALLOW_SOURCE", "0") == "1"
UPDATE_STATE_FILE = DATA_DIR / "update_state.json"
UPDATE_INSTALL_DIR = DATA_DIR / "updates"
UPDATE_CHECK_TTL_HOURS = float(os.environ.get("SF_UPDATE_CHECK_HOURS", "6"))

MAX_WORKERS = 5
DEFAULT_WORKERS = 3


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime configuration, built once in ``main()`` and injected."""

    org_base: str
    data_dir: Path
    db_path: Path
    workers: int
    refresh_interval_s: float
    request_timeout_ms: int
    login_wait_s: int
    headless: bool
    update_policy: str
    host: str = "0.0.0.0"
    port: int = 8765
    dev_tools: bool = True
    dev_tools_allow_remote: bool = False


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_settings() -> Settings:
    workers = min(MAX_WORKERS, max(1, _env_int("SF_DEVIATION_WORKERS", DEFAULT_WORKERS)))
    return Settings(
        org_base=ORG_BASE,
        data_dir=DATA_DIR,
        db_path=DB_PATH,
        workers=workers,
        refresh_interval_s=float(_env_int("SF_RESYNC_INTERVAL_SECONDS", 30)),
        request_timeout_ms=REQUEST_TIMEOUT_MS,
        login_wait_s=LOGIN_WAIT_SECONDS,
        headless=os.environ.get("SF_HEADLESS", "1") != "0",
        update_policy=UPDATE_POLICY,
        host=HOST,
        port=PORT,
        dev_tools=os.environ.get("SF_DEV_TOOLS", "1") != "0",
        dev_tools_allow_remote=os.environ.get("SF_DEV_TOOLS_ALLOW_REMOTE", "0")
        == "1",
    )
