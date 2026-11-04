"""SQLite schema for the workflow store (schema v2).

Every item table is workflow-scoped: ``workflow`` is part of each primary key, so several
workflows share the same tables without interfering. See docs/class-design-deviations.md.
"""

from __future__ import annotations

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS work_items (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    record_url TEXT,
    status TEXT NOT NULL,
    source TEXT,
    reason TEXT,
    present INTEGER NOT NULL DEFAULT 1,
    epoch INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    absent_since TEXT,
    approved_at TEXT,
    extracted_at TEXT,
    execute_attempted_at TEXT,
    execute_confirmed_at TEXT,
    closed_at TEXT,
    PRIMARY KEY (workflow, item_key)
);
CREATE INDEX IF NOT EXISTS work_items_status ON work_items(workflow, status);

CREATE TABLE IF NOT EXISTS work_item_fields (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    extracted TEXT,
    last_synced TEXT,
    proposed TEXT,
    applied TEXT,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workflow, item_key, field_key)
);

CREATE TABLE IF NOT EXISTS work_item_attributes (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (workflow, item_key, name)
);

CREATE TABLE IF NOT EXISTS work_item_refs (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    PRIMARY KEY (workflow, item_key, kind)
);

CREATE TABLE IF NOT EXISTS work_item_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    job_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_item_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT,
    item_key TEXT,
    job_id INTEGER,
    kind TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS jobs_claim ON jobs(status, kind, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_active ON jobs(workflow, item_key)
    WHERE status IN ('queued', 'running', 'blocked_auth');

CREATE TABLE IF NOT EXISTS job_logs (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    line TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (job_id, seq)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    header_total INTEGER,
    rows_read INTEGER NOT NULL,
    valid INTEGER NOT NULL,
    warning TEXT,
    added INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org TEXT,
    storage_state TEXT NOT NULL,
    cookie_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""
