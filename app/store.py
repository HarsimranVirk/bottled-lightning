"""SQLite persistence: tracked views, job history, extracted rows."""
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

_local = threading.local()


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS views (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    url         TEXT NOT NULL,
    pattern     TEXT NOT NULL DEFAULT 'Deviation-\\d+-\\d+',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    view_id     INTEGER NOT NULL REFERENCES views(id),
    status      TEXT NOT NULL,             -- running|success|failed
    detail      TEXT,                      -- human message / error
    header_total INTEGER,
    extracted    INTEGER,
    started_at   TEXT NOT NULL,
    finished_at  TEXT
);
CREATE TABLE IF NOT EXISTS job_rows (
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    value      TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    UNIQUE(job_id, value)
);
CREATE TABLE IF NOT EXISTS latest_values (
    view_id   INTEGER NOT NULL REFERENCES views(id),
    value     TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    PRIMARY KEY(view_id, value)
);
"""


def init_db() -> None:
    conn = _conn()
    conn.executescript(SCHEMA)
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- views -----------------------------------------------------------------
def add_view(name: str, url: str, pattern: str) -> Dict[str, Any]:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO views(name, url, pattern, created_at) VALUES (?,?,?,?)",
        (name, url, pattern, now_iso()),
    )
    conn.commit()
    return dict(get_view(cur.lastrowid))


def get_view(view_id: int) -> Optional[sqlite3.Row]:
    return _conn().execute("SELECT * FROM views WHERE id=?", (view_id,)).fetchone()


def list_views() -> List[Dict[str, Any]]:
    rows = _conn().execute(
        "SELECT v.*, "
        " (SELECT COUNT(*) FROM latest_values lv WHERE lv.view_id=v.id) AS latest_count,"
        " (SELECT MAX(j.started_at) FROM jobs j WHERE j.view_id=v.id AND j.status='success') AS last_success"
        " FROM views v ORDER BY v.id"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_view(view_id: int) -> bool:
    conn = _conn()
    cur = conn.execute("DELETE FROM views WHERE id=?", (view_id,))
    conn.execute("DELETE FROM latest_values WHERE view_id=?", (view_id,))
    conn.commit()
    return cur.rowcount > 0


# --- jobs ------------------------------------------------------------------
def create_job(view_id: int) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO jobs(view_id, status, started_at) VALUES (?, 'running', ?)",
        (view_id, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def finish_job(job_id: int, status: str, detail: str = "", header_total: Optional[int] = None,
               extracted: Optional[int] = None) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE jobs SET status=?, detail=?, header_total=?, extracted=?, finished_at=?"
        " WHERE id=?",
        (status, detail, header_total, extracted, now_iso(), job_id),
    )
    conn.commit()


def get_job(job_id: int) -> Optional[Dict[str, Any]]:
    row = _conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    rows = _conn().execute(
        "SELECT j.*, v.name AS view_name FROM jobs j JOIN views v ON v.id=j.view_id"
        " ORDER BY j.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- rows ------------------------------------------------------------------
def record_rows(view_id: int, job_id: int, values: List[str]) -> int:
    """Insert into snapshot + latest_values; returns number of rows recorded."""
    conn = _conn()
    ts = now_iso()
    for v in set(values):
        conn.execute(
            "INSERT OR IGNORE INTO job_rows(job_id, value, snapshot_at) VALUES (?,?,?)",
            (job_id, v, ts),
        )
        conn.execute(
            "INSERT INTO latest_values(view_id, value, first_seen, last_seen)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(view_id, value) DO UPDATE SET last_seen=excluded.last_seen",
            (view_id, v, ts, ts),
        )
    conn.commit()
    return len(set(values))


def latest_values(view_id: int) -> List[Dict[str, Any]]:
    rows = _conn().execute(
        "SELECT value, first_seen, last_seen FROM latest_values"
        " WHERE view_id=? ORDER BY value",
        (view_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def job_rows(job_id: int) -> List[Dict[str, Any]]:
    rows = _conn().execute(
        "SELECT value, snapshot_at FROM job_rows WHERE job_id=? ORDER BY value",
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]
