"""Project settings, overridable via environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

ORG_BASE = os.environ.get("SF_ORG_BASE", "https://hffc.lightning.force.com")
API_HOST = os.environ.get(
    "SF_API_HOST", ORG_BASE.replace(".lightning.force.com", ".my.salesforce.com")
)

DATA_DIR = Path(os.environ.get("SF_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_DIR = DATA_DIR / "sf_profile"
AUTH_FILE = DATA_DIR / "auth.json"
DB_PATH = DATA_DIR / "app.db"

LIST_HOST_ROOT = f"{ORG_BASE}/lightning/o/"
LIST_URL_TEMPLATE = "{host}/lightning/o/{object_api}/list?filterName={filter}"

REQUEST_TIMEOUT_MS = 60_000
LOGIN_WAIT_SECONDS = 600

SCRAPE_WORKERS = int(os.environ.get("SF_SCRAPE_WORKERS", "3"))

# Server host/port (badly-named env prefix kept for consistency)
HOST = os.environ.get("SF_HOST", "0.0.0.0")  # 0.0.0.0 → reachable on LAN
PORT = int(os.environ.get("SF_PORT", "8765"))
