"""SQLite persistence (data/app.db) — the app's general-purpose store.

Tables: views, jobs, job_rows, latest_values, session_events, sessions
(auth snapshots). Thread-local connections; WAL mode.
"""
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
CREATE TABLE IF NOT EXISTS session_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event      TEXT NOT NULL,            -- login_started|login_success|login_failed|login_timed_out|session_reset
    detail     TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    org           TEXT NOT NULL,
    storage_state TEXT NOT NULL,         -- Playwright storage_state JSON (contains live sid cookie)
    cookie_count  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deviation_details (
    value          TEXT PRIMARY KEY,     -- deviation number, e.g. Deviation-28102026-484106
    record_id      TEXT,                 -- Salesforce record key (a2fS...)
    record_url     TEXT,                 -- /lightning/r/.../view
    description    TEXT,                 -- raw 'Loan Deviation Description' block
    property_value TEXT,
    loan_amount    TEXT,
    tenure         TEXT,
    emi            TEXT,
    scraped_at     TEXT,
    decision       TEXT NOT NULL DEFAULT 'pending',  -- pending|accept|reject
    decided_at     TEXT
);
CREATE TABLE IF NOT EXISTS deviation_page_refs (
    value      TEXT NOT NULL REFERENCES deviation_details(value),
    seq        INTEGER NOT NULL,         -- ordering for traversal workflows
    name       TEXT NOT NULL,            -- human label (Opportunity, SD contract, ...)
    kind       TEXT NOT NULL,            -- record|opportunity|service|custom — extensible
    url        TEXT NOT NULL,            -- page reference (relative lightning URL ok)
    created_at TEXT NOT NULL,
    PRIMARY KEY (value, seq)
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


# --- session events -----------------------------------------------------------
def record_session_event(event: str, detail: str = "") -> Dict[str, Any]:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO session_events(event, detail, created_at) VALUES (?,?,?)",
        (event, detail, now_iso()),
    )
    conn.commit()
    row = _conn().execute("SELECT * FROM session_events WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def last_session_event(event: str) -> Optional[Dict[str, Any]]:
    row = _conn().execute(
        "SELECT * FROM session_events WHERE event=? ORDER BY id DESC LIMIT 1", (event,)
    ).fetchone()
    return dict(row) if row else None


def list_session_events(limit: int = 10) -> List[Dict[str, Any]]:
    rows = _conn().execute(
        "SELECT * FROM session_events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# --- auth session snapshot (DB is authoritative; auth.json is legacy) ---------
def set_auth_snapshot(storage_state: str, org: Optional[str] = None) -> int:
    """Persist a Playwright storage_state JSON blob as the current session."""
    try:
        cookie_count = len(json.loads(storage_state).get("cookies", []))
    except (ValueError, AttributeError):
        cookie_count = 0
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO sessions(org, storage_state, cookie_count, created_at)"
        " VALUES (?,?,?,?)",
        (org or config.ORG_BASE, storage_state, cookie_count, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def get_auth_snapshot() -> Optional[Dict[str, Any]]:
    """Latest stored session row (raw storage_state JSON included)."""
    row = _conn().execute(
        "SELECT id, org, storage_state, cookie_count, created_at"
        " FROM sessions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def clear_auth_snapshot() -> int:
    conn = _conn()
    cur = conn.execute("DELETE FROM sessions")
    conn.commit()
    return cur.rowcount


# --- deviation details + page refs --------------------------------------------
def upsert_deviation_detail(value: str, *, record_id: Optional[str] = None,
                            record_url: Optional[str] = None,
                            description: Optional[str] = None,
                            property_value: Optional[str] = None,
                            loan_amount: Optional[str] = None,
                            tenure: Optional[str] = None,
                            emi: Optional[str] = None) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO deviation_details(value) VALUES (?)"
        " ON CONFLICT(value) DO NOTHING", (value,))
    data: Dict[str, Any] = {"scraped_at": now_iso()}
    for key, val in (("record_id", record_id), ("record_url", record_url),
                     ("description", description),
                     ("property_value", property_value),
                     ("loan_amount", loan_amount), ("tenure", tenure),
                     ("emi", emi)):
        if val is not None:
            data[key] = val
    if len(data) > 1:
        sets = ", ".join(f"{k}=?" for k in data)
        conn.execute(f"UPDATE deviation_details SET {sets} WHERE value=?",
                     (*data.values(), value))
    conn.commit()


def set_deviation_decision(value: str, decision: str) -> None:
    assert decision in ("pending", "accept", "reject")
    conn = _conn()
    conn.execute(
        "INSERT INTO deviation_details(value) VALUES (?)"
        " ON CONFLICT(value) DO NOTHING", (value,))
    decided = None if decision == "pending" else now_iso()
    conn.execute(
        "UPDATE deviation_details SET decision=?, decided_at=? WHERE value=?",
        (decision, decided, value))
    conn.commit()


def get_deviation_details(value: str) -> Optional[Dict[str, Any]]:
    row = _conn().execute(
        "SELECT * FROM deviation_details WHERE value=?", (value,)).fetchone()
    return dict(row) if row else None


def count_pending_details(pending_only: bool = True) -> List[Dict[str, Any]]:
    """Values with a description scraped but not yet decided (deck queue)."""
    sql = ("SELECT d.*, l.first_seen, l.last_seen FROM deviation_details d"
           " LEFT JOIN latest_values l ON l.value = d.value")
    if pending_only:
        sql += " WHERE d.decision='pending'"
    rows = _conn().execute(sql).fetchall()
    return [dict(r) for r in rows]


def upsert_deviation_page_ref(value: str, seq: int, name: str, kind: str,
                             url: str) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO deviation_page_refs(value, seq, name, kind, url, created_at)"
        " VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(value, seq) DO UPDATE SET name=excluded.name,"
        " kind=excluded.kind, url=excluded.url",
        (value, seq, name, kind, url, now_iso()))
    conn.commit()


def get_deviation_page_refs(value: str) -> List[Dict[str, Any]]:
    rows = _conn().execute(
        "SELECT seq, name, kind, url FROM deviation_page_refs"
        " WHERE value=? ORDER BY seq", (value,)).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print(f"sqlite initialized: {config.DB_PATH}")
