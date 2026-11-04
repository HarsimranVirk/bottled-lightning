"""Settings (org URLs, data dir, update policy; env-overridable)."""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SF_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
PROFILE_DIR = DATA_DIR / "sf_profile"
AUTH_FILE = DATA_DIR / "auth.json"
ORG_BASE = os.environ.get("SF_ORG_BASE", "https://hffc.lightning.force.com")
LIST_HOST_ROOT = f"{ORG_BASE}/lightning/o/"
LIST_URL_TEMPLATE = "{host}/lightning/o/{object_api}/list?filterName={filter}"
REQUEST_TIMEOUT_MS = 60_000
LOGIN_WAIT_SECONDS = 600
HOST = os.environ.get("SF_HOST", "0.0.0.0")
PORT = int(os.environ.get("SF_PORT", "8765"))
IS_SOURCE_CHECKOUT = (BASE_DIR / "frontend" / "src").exists()
UPDATE_POLICY = os.environ.get("SF_UPDATE_POLICY", "auto")
UPDATE_AUTO_START = True
UPDATE_ALLOW_SOURCE = os.environ.get("SF_UPDATE_ALLOW_SOURCE", "0") == "1"
SCRAPE_WORKERS = int(os.environ.get("SF_SCRAPE_WORKERS", "3"))
SETTINGS_FILE = DATA_DIR / "settings.json"
UPDATE_STATE_FILE = DATA_DIR / "update_state.json"

# Continuous queue resync: one list-view visit every RESYNC_INTERVAL_SECONDS.
RESYNC_INTERVAL_SECONDS = int(os.environ.get("SF_RESYNC_INTERVAL_SECONDS", "30"))
RESYNC_AUTO_START = os.environ.get("SF_RESYNC_AUTO_START", "1") == "1"
# A deviation whose detail extraction failed is retried at most this often.
RESYNC_RETRY_COOLDOWN_SECONDS = int(os.environ.get("SF_RESYNC_RETRY_COOLDOWN_SECONDS", "600"))
# How long an extraction job waits for the first sync snapshot before failing.
RESYNC_SNAPSHOT_WAIT_SECONDS = int(os.environ.get("SF_RESYNC_SNAPSHOT_WAIT_SECONDS", "120"))
# The sync loop owns this profile so it never clashes with the manual login window.
SYNC_PROFILE_DIR = DATA_DIR / "sf_profile_sync"


def _load_scrape_workers() -> int:
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        n = int(data.get("scrape_workers", SCRAPE_WORKERS))
        if 1 <= n <= 32:
            return n
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return SCRAPE_WORKERS


SCRAPE_WORKERS = _load_scrape_workers()


def set_scrape_workers(count: int) -> int:
    global SCRAPE_WORKERS
    n = int(count)
    if not (1 <= n <= 32):
        raise ValueError("scrape workers must be between 1 and 32")
    SCRAPE_WORKERS = n
    try:
        SETTINGS_FILE.write_text(json.dumps({"scrape_workers": n}))
    except OSError:
        pass
    return SCRAPE_WORKERS
