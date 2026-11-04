"""SQLite store."""

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from . import config

Decision = Literal["pending", "accept", "reject"]

_local = threading.local()


def _conn() -> sqlite3.Connection:
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    pattern TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    view_id INTEGER NOT NULL REFERENCES views(id),
    status TEXT NOT NULL,
    detail TEXT,
    header_total INTEGER,
    extracted INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS job_rows (
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    value TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    PRIMARY KEY(job_id, value)
);
CREATE TABLE IF NOT EXISTS latest_values (
    view_id INTEGER NOT NULL REFERENCES views(id),
    value TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    approval_date TEXT,
    PRIMARY KEY(view_id, value)
);

CREATE TABLE IF NOT EXISTS deviation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT NOT NULL,
    sf_approval_date TEXT,
    decided_at TEXT,
    archived_at TEXT NOT NULL,
    record_id TEXT,
    record_url TEXT,
    description TEXT,
    property_value TEXT,
    loan_amount TEXT,
    tenure TEXT,
    emi TEXT,
    requested_roi TEXT,
    ideal_roi TEXT,
    updated_roi TEXT,
    requested_variance TEXT,
    opportunity_url TEXT,
    cl_contract_url TEXT,
    collateral_url TEXT,
    lms2_collateral_url TEXT,
    lms2_cl_contract_url TEXT,
    page_refs_json TEXT
);
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org TEXT,
    storage_state TEXT NOT NULL,
    cookie_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deviation_details (
    value TEXT PRIMARY KEY,
    record_id TEXT,
    record_url TEXT,
    description TEXT,
    property_value TEXT,
    loan_amount TEXT,
    tenure TEXT,
    emi TEXT,
    requested_roi TEXT,
    ideal_roi TEXT,
    updated_roi TEXT,
    requested_variance TEXT,
    opportunity_url TEXT,
    cl_contract_url TEXT,
    collateral_url TEXT,
    lms2_collateral_url TEXT,
    lms2_cl_contract_url TEXT,
    scraped_at TEXT,
    extracted_at TEXT,
    decision TEXT NOT NULL DEFAULT 'pending',
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS deviation_page_refs (
    value TEXT NOT NULL,
    seq INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (value, seq)
);
CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    line TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def init_db() -> None:
    conn = _conn()
    conn.executescript(SCHEMA)
    for col in (
        "requested_roi",
        "ideal_roi",
        "updated_roi",
        "requested_variance",
        "opportunity_url",
        "cl_contract_url",
        "collateral_url",
        "lms2_collateral_url",
        "lms2_cl_contract_url",
        "approval_date",
        "extracted_at",
    ):
        try:
            conn.execute(f"ALTER TABLE deviation_details ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    # latest_values.approval_date
    try:
        conn.execute("ALTER TABLE latest_values ADD COLUMN approval_date TEXT")
    except sqlite3.OperationalError:
        pass
    # backfill the one-shot marker so upgrades don't re-scrape existing rows
    conn.execute(
        "UPDATE deviation_details SET extracted_at=scraped_at"
        " WHERE extracted_at IS NULL AND scraped_at IS NOT NULL"
    )
    conn.commit()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --- views ---
def add_view(name: str, url: str, pattern: str) -> dict[str, str | int | None]:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO views(name, url, pattern, created_at) VALUES (?,?,?,?)",
        (name, url, pattern, now_iso()),
    )
    conn.commit()
    view_id = cur.lastrowid
    if view_id is None:
        raise RuntimeError("failed to insert view")
    view = get_view(view_id)
    if view is None:
        raise RuntimeError("failed to read back inserted view")
    return dict(view)


def delete_view(view_id: int) -> bool:
    conn = _conn()
    cur = conn.execute("DELETE FROM views WHERE id=?", (view_id,))
    conn.commit()
    return cur.rowcount > 0


def get_view(view_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = (
        _conn().execute("SELECT * FROM views WHERE id=?", (view_id,)).fetchone()
    )
    return row


def list_views() -> list[dict[str, str | int | None]]:
    rows = (
        _conn()
        .execute(
            "SELECT v.*, "
            " (SELECT COUNT(*) FROM latest_values lv WHERE lv.view_id=v.id) AS latest_count,"
            " (SELECT MAX(j.started_at) FROM jobs j "
            "WHERE j.view_id=v.id AND j.status='success') AS last_success"
            " FROM views v ORDER BY v.id"
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


# --- jobs ---
def create_job(view_id: int) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO jobs(view_id, status, started_at) VALUES (?,?,?)",
        (view_id, "running", now_iso()),
    )
    conn.commit()
    job_id = cur.lastrowid
    if job_id is None:
        raise RuntimeError("failed to insert job")
    return job_id


def finish_job(
    job_id: int,
    status: str,
    detail: str = "",
    header_total: int | None = None,
    extracted: int | None = None,
) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE jobs SET status=?, detail=?, header_total=?, extracted=?, finished_at=? WHERE id=?",
        (status, detail, header_total, extracted, now_iso(), job_id),
    )
    conn.commit()


def get_job(job_id: int) -> dict[str, str | int | None] | None:
    row = _conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 50) -> list[dict[str, str | int | None]]:
    rows = (
        _conn()
        .execute(
            "SELECT j.*, v.name AS view_name FROM jobs j JOIN views v ON v.id=j.view_id"
            " ORDER BY j.id DESC LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def running_jobs(stale_after_seconds: int = 6 * 3600) -> int:
    rows = _conn().execute("SELECT started_at FROM jobs WHERE status='running'").fetchall()
    cutoff = datetime.now(UTC).timestamp() - stale_after_seconds
    active = 0
    for row in rows:
        try:
            started = datetime.fromisoformat(row["started_at"]).timestamp()
        except ValueError:
            started = 0
        if started >= cutoff:
            active += 1
    return active


def fail_stale_running_jobs() -> int:
    conn = _conn()
    rows = conn.execute("SELECT id FROM jobs WHERE status='running'").fetchall()
    ids = [int(r["id"]) for r in rows]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE jobs SET status='failed', detail=?, finished_at=? WHERE id IN ({placeholders})",
        ("interrupted: app restarted while job was running", now_iso(), *ids),
    )
    conn.commit()
    return len(ids)


# --- rows ---
def record_rows(
    view_id: int,
    job_id: int,
    values: Iterable[str],
    approval_dates: dict[str, str] | None = None,
) -> int:
    ad = approval_dates or {}
    conn = _conn()
    ts = now_iso()
    unique_values = set(values)
    for v in unique_values:
        conn.execute(
            "INSERT OR IGNORE INTO job_rows(job_id, value, snapshot_at) VALUES (?,?,?)",
            (job_id, v, ts),
        )
        conn.execute(
            "INSERT INTO latest_values(view_id, value, first_seen, last_seen, approval_date)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(view_id, value) DO UPDATE SET last_seen=excluded.last_seen,"
            " approval_date=COALESCE(excluded.approval_date, latest_values.approval_date)",
            (view_id, v, ts, ts, ad.get(v)),
        )
    conn.commit()
    return len(unique_values)


def latest_values(view_id: int) -> list[dict[str, str]]:
    rows = (
        _conn()
        .execute(
            "SELECT value, first_seen, last_seen FROM latest_values WHERE view_id=? ORDER BY value",
            (view_id,),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def job_rows(job_id: int) -> list[dict[str, str]]:
    rows = (
        _conn()
        .execute(
            "SELECT value, snapshot_at FROM job_rows WHERE job_id=? ORDER BY value",
            (job_id,),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


# --- session events ---
def record_session_event(event: str, detail: str = "") -> dict[str, str | int]:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO session_events(event, detail, created_at) VALUES (?,?,?)",
        (event, detail, now_iso()),
    )
    conn.commit()
    event_id = cur.lastrowid
    if event_id is None:
        raise RuntimeError("failed to insert session event")
    row = _conn().execute("SELECT * FROM session_events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        raise RuntimeError("failed to read back inserted session event")
    return dict(row)


def last_session_event(event: str) -> dict[str, str | int] | None:
    row = (
        _conn()
        .execute("SELECT * FROM session_events WHERE event=? ORDER BY id DESC LIMIT 1", (event,))
        .fetchone()
    )
    return dict(row) if row else None


def list_session_events(limit: int = 10) -> list[dict[str, str | int]]:
    rows = (
        _conn()
        .execute("SELECT * FROM session_events ORDER BY id DESC LIMIT ?", (limit,))
        .fetchall()
    )
    return [dict(r) for r in rows]


# --- auth session snapshot ---
def set_auth_snapshot(storage_state: str, org: str | None = None) -> int:
    try:
        cookie_count = len(json.loads(storage_state).get("cookies", []))
    except json.JSONDecodeError, AttributeError, TypeError:
        cookie_count = 0
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO sessions(org, storage_state, cookie_count, created_at) VALUES (?,?,?,?)",
        (org or config.ORG_BASE, storage_state, cookie_count, now_iso()),
    )
    conn.commit()
    snapshot_id = cur.lastrowid
    if snapshot_id is None:
        raise RuntimeError("failed to insert auth snapshot")
    return snapshot_id


def get_auth_snapshot() -> dict[str, str | int] | None:
    row = (
        _conn()
        .execute(
            "SELECT id, org, storage_state, cookie_count, created_at"
            " FROM sessions ORDER BY id DESC LIMIT 1"
        )
        .fetchone()
    )
    return dict(row) if row else None


def clear_auth_snapshot() -> int:
    conn = _conn()
    cur = conn.execute("DELETE FROM sessions")
    conn.commit()
    return cur.rowcount


# --- deviation details + page refs ---
def upsert_deviation_detail(
    value: str,
    *,
    record_id: str | None = None,
    record_url: str | None = None,
    description: str | None = None,
    property_value: str | None = None,
    loan_amount: str | None = None,
    tenure: str | None = None,
    emi: str | None = None,
    requested_roi: str | None = None,
    ideal_roi: str | None = None,
    updated_roi: str | None = None,
    requested_variance: str | None = None,
    opportunity_url: str | None = None,
    cl_contract_url: str | None = None,
    collateral_url: str | None = None,
    lms2_collateral_url: str | None = None,
    lms2_cl_contract_url: str | None = None,
) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO deviation_details(value) VALUES (?) ON CONFLICT(value) DO NOTHING", (value,)
    )
    data: dict[str, str] = {"scraped_at": now_iso()}
    for key, val in (
        ("record_id", record_id),
        ("record_url", record_url),
        ("description", description),
        ("property_value", property_value),
        ("loan_amount", loan_amount),
        ("tenure", tenure),
        ("emi", emi),
        ("requested_roi", requested_roi),
        ("ideal_roi", ideal_roi),
        ("updated_roi", updated_roi),
        ("requested_variance", requested_variance),
        ("opportunity_url", opportunity_url),
        ("cl_contract_url", cl_contract_url),
        ("collateral_url", collateral_url),
        ("lms2_collateral_url", lms2_collateral_url),
        ("lms2_cl_contract_url", lms2_cl_contract_url),
    ):
        if val is not None:
            data[key] = val
    if len(data) > 1:
        sets = ", ".join(f"{k}=?" for k in data)
        conn.execute(f"UPDATE deviation_details SET {sets} WHERE value=?", (*data.values(), value))
    conn.commit()


def mark_deviation_extracted(value: str) -> None:
    """Record that the record was visited; queued deviations are immutable in practice."""
    conn = _conn()
    conn.execute(
        "INSERT INTO deviation_details(value) VALUES (?) ON CONFLICT(value) DO NOTHING", (value,)
    )
    conn.execute("UPDATE deviation_details SET extracted_at=? WHERE value=?", (now_iso(), value))
    conn.commit()


def set_deviation_decision(value: str, decision: Decision) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO deviation_details(value) VALUES (?) ON CONFLICT(value) DO NOTHING", (value,)
    )
    decided = None if decision == "pending" else now_iso()
    conn.execute(
        "UPDATE deviation_details SET decision=?, decided_at=? WHERE value=?",
        (decision, decided, value),
    )
    conn.commit()


def archive_accepted_deviation(value: str) -> int:
    det = get_deviation_details(value)
    if det is None:
        return 0
    refs = get_deviation_page_refs(value)
    page_refs_json = json.dumps(refs)
    # sf approval date lives in latest_values
    sf_approval = None
    lr = (
        _conn()
        .execute("SELECT approval_date FROM latest_values WHERE value=? LIMIT 1", (value,))
        .fetchone()
    )
    if lr is not None:
        sf_approval = lr["approval_date"]
    decided_at = det.get("decided_at")
    conn = _conn()
    existing = conn.execute(
        "SELECT id FROM deviation_history WHERE value=? AND decided_at IS ?",
        (value, decided_at),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])
    cur = conn.execute(
        "INSERT INTO deviation_history("
        "value, sf_approval_date, decided_at, archived_at,"
        "record_id, record_url, description, property_value, loan_amount, tenure, emi,"
        "requested_roi, ideal_roi, updated_roi, requested_variance,"
        "opportunity_url, cl_contract_url, collateral_url, lms2_collateral_url, lms2_cl_contract_url,"
        "page_refs_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            value,
            sf_approval,
            decided_at,
            now_iso(),
            det.get("record_id"),
            det.get("record_url"),
            det.get("description"),
            det.get("property_value"),
            det.get("loan_amount"),
            det.get("tenure"),
            det.get("emi"),
            det.get("requested_roi"),
            det.get("ideal_roi"),
            det.get("updated_roi"),
            det.get("requested_variance"),
            det.get("opportunity_url"),
            det.get("cl_contract_url"),
            det.get("collateral_url"),
            det.get("lms2_collateral_url"),
            det.get("lms2_cl_contract_url"),
            page_refs_json,
        ),
    )
    conn.commit()
    if cur.lastrowid is None:
        return 0
    return int(cur.lastrowid)


def delete_deviation_active(value: str) -> None:
    conn = _conn()
    conn.execute("DELETE FROM latest_values WHERE value=?", (value,))
    conn.execute("DELETE FROM deviation_page_refs WHERE value=?", (value,))
    conn.execute("DELETE FROM deviation_details WHERE value=?", (value,))
    conn.commit()


def list_deviation_history(
    filters: dict[str, str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, object]], int]:
    filters = filters or {}
    allowed = {
        "value",
        "sf_approval_date",
        "decided_at",
        "record_id",
        "description",
        "property_value",
        "loan_amount",
        "tenure",
        "emi",
        "requested_roi",
        "ideal_roi",
        "updated_roi",
        "requested_variance",
        "opportunity_url",
        "cl_contract_url",
        "collateral_url",
        "lms2_collateral_url",
        "lms2_cl_contract_url",
    }
    where: list[str] = []
    params: list[object] = []
    for key, val in filters.items():
        if key not in allowed:
            continue
        if val == "":
            continue
        where.append(f"{key} LIKE ?")
        params.append(f"%{val}%")
    # date range filters
    decided_from = filters.get("decided_from")
    if decided_from:
        where.append("decided_at >= ?")
        params.append(decided_from)
    decided_to = filters.get("decided_to")
    if decided_to:
        where.append("decided_at <= ?")
        params.append(decided_to)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = (
        _conn().execute(f"SELECT COUNT(*) AS c FROM deviation_history{clause}", params).fetchone()
    )
    total = int(total_row["c"]) if total_row is not None else 0
    rows = (
        _conn()
        .execute(
            f"SELECT * FROM deviation_history{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        .fetchall()
    )
    return [dict(r) for r in rows], total


def get_deviation_details(value: str) -> dict[str, str | None] | None:
    row = _conn().execute("SELECT * FROM deviation_details WHERE value=?", (value,)).fetchone()
    return dict(row) if row else None


def count_pending_details(pending_only: bool = True) -> list[dict[str, str | None]]:
    sql = (
        "SELECT d.*, l.first_seen, l.last_seen FROM deviation_details d"
        " LEFT JOIN latest_values l ON l.value = d.value"
    )
    if pending_only:
        sql += " WHERE d.decision='pending'"
    rows = _conn().execute(sql).fetchall()
    return [dict(r) for r in rows]


def upsert_deviation_page_ref(value: str, seq: int, name: str, kind: str, url: str) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO deviation_page_refs(value, seq, name, kind, url, created_at)"
        " VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(value, seq) DO UPDATE SET name=excluded.name,"
        " kind=excluded.kind, url=excluded.url",
        (value, seq, name, kind, url, now_iso()),
    )
    conn.commit()


_ALLOWED_PAGE_REF_KINDS = frozenset(
    {
        "opportunity",
        "cl_contract",
        "collateral",
        "lms2_collateral",
        "lms2_cl_contract",
    }
)


def delete_deviation_page_refs(value: str) -> None:
    conn = _conn()
    conn.execute("DELETE FROM deviation_page_refs WHERE value=?", (value,))
    conn.commit()


def get_deviation_page_refs(value: str) -> list[dict[str, str | int]]:
    rows = (
        _conn()
        .execute(
            "SELECT seq, name, kind, url FROM deviation_page_refs WHERE value=? ORDER BY seq",
            (value,),
        )
        .fetchall()
    )
    seen: set[str] = set()
    out: list[dict[str, str | int]] = []
    for r in rows:
        kind = str(r["kind"])
        if kind not in _ALLOWED_PAGE_REF_KINDS:
            continue
        if kind in seen:
            continue
        seen.add(kind)
        out.append(dict(r))
    return out


def resync_queue(
    view_id: int,
    sf_values: Iterable[str],
    approval_dates: dict[str, str] | None = None,
) -> dict[str, int | list[str]]:
    ad = approval_dates or {}
    conn = _conn()
    ts = now_iso()
    sf_set = {str(v).strip() for v in sf_values if str(v).strip()}

    current_rows = (
        _conn()
        .execute(
            "SELECT value, first_seen FROM latest_values WHERE view_id=?",
            (view_id,),
        )
        .fetchall()
    )
    current = {str(r["value"]): str(r["first_seen"]) for r in current_rows}

    added: list[str] = []
    kept: list[str] = []
    for value in sf_set:
        if value in current:
            if value in ad:
                conn.execute(
                    "UPDATE latest_values SET last_seen=?, approval_date=? WHERE view_id=? AND value=?",
                    (ts, ad[value], view_id, value),
                )
            else:
                conn.execute(
                    "UPDATE latest_values SET last_seen=? WHERE view_id=? AND value=?",
                    (ts, view_id, value),
                )
            kept.append(value)
        else:
            conn.execute(
                "INSERT INTO latest_values(view_id, value, first_seen, last_seen, approval_date)"
                " VALUES (?,?,?,?,?)",
                (view_id, value, ts, ts, ad.get(value)),
            )
            added.append(value)

    removed: list[str] = []
    for value in current:
        if value not in sf_set:
            conn.execute(
                "DELETE FROM latest_values WHERE view_id=? AND value=?",
                (view_id, value),
            )
            removed.append(value)

    conn.commit()
    return {
        "view_id": view_id,
        "added": sorted(added),
        "removed": sorted(removed),
        "kept": len(kept),
        "total": len(sf_set),
    }


# aliases
resync_latest_values = resync_queue
refresh_queue = resync_queue
refresh_latest_values = resync_queue
sync_queue = resync_queue
sync_latest_values = resync_queue
reconcile_queue = resync_queue
reconcile_latest_values = resync_queue
update_queue = resync_queue
update_latest_values = resync_queue
resync = resync_queue
refresh = resync_queue
sync = resync_queue


def append_job_log(job_id: int, line: str) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO job_logs(job_id, line, created_at) VALUES (?,?,?)",
        (job_id, line, now_iso()),
    )
    conn.commit()


def get_job_logs(job_id: int, limit: int = 5000) -> list[str]:
    rows = (
        _conn()
        .execute(
            "SELECT line FROM job_logs WHERE job_id=? ORDER BY id LIMIT ?",
            (job_id, limit),
        )
        .fetchall()
    )
    return [str(r["line"]) for r in rows]


if __name__ == "__main__":
    pass
