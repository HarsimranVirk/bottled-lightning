"""SQLite schema for the workflow store.

Every item table is workflow-scoped: ``workflow`` is part of each primary key, so several
workflows share the same tables without interfering. See docs/class-design-deviations.md.
"""

from __future__ import annotations

SCHEMA_VERSION = 6

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
    state TEXT NOT NULL DEFAULT 'found',
    reason TEXT,
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
CREATE INDEX IF NOT EXISTS jobs_item ON jobs(item_key);
CREATE INDEX IF NOT EXISTS jobs_started ON jobs(started_at);
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

CREATE TABLE IF NOT EXISTS item_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'pending')),
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS item_decisions_latest
    ON item_decisions(workflow, item_key, id DESC);

CREATE TABLE IF NOT EXISTS approved_deviations (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    epoch INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    source TEXT,
    present INTEGER NOT NULL DEFAULT 1,
    record_url TEXT,
    approved_at TEXT,
    reason TEXT,
    decided_at TEXT NOT NULL,
    decision_reason TEXT,
    snapshot_at TEXT NOT NULL,
    PRIMARY KEY (workflow, item_key)
);
CREATE INDEX IF NOT EXISTS approved_deviations_decided
    ON approved_deviations(decided_at);
CREATE INDEX IF NOT EXISTS approved_deviations_workflow_decided
    ON approved_deviations(workflow, decided_at DESC);

CREATE TABLE IF NOT EXISTS approved_deviation_fields (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    extracted TEXT,
    last_synced TEXT,
    proposed TEXT,
    applied TEXT,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workflow, item_key, field_key),
    FOREIGN KEY (workflow, item_key)
        REFERENCES approved_deviations(workflow, item_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS approved_deviation_attributes (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (workflow, item_key, name),
    FOREIGN KEY (workflow, item_key)
        REFERENCES approved_deviations(workflow, item_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS approved_deviation_refs (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'found',
    reason TEXT,
    PRIMARY KEY (workflow, item_key, kind),
    FOREIGN KEY (workflow, item_key)
        REFERENCES approved_deviations(workflow, item_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS approved_deviation_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workflow, item_key)
        REFERENCES approved_deviations(workflow, item_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS approved_deviation_edits_item
    ON approved_deviation_edits(workflow, item_key, id DESC);
"""

#: One-time v5 -> v6 status migration.
#:
#: Extraction no longer parks work in ``skipped``: a row that could not produce a
#: complete extraction lands in ``needs_review`` instead. The one legacy case that is
#: not operator work is the missing-record-URL skip — that row simply had no link yet,
#: so it returns to ``present`` and the reconciler queues extraction when the link
#: appears. Ordering matters: the first statement matches only that exact legacy reason.
BACKFILL_V6_STATUSES = (
    """
    UPDATE work_items
       SET status = 'present', reason = NULL
     WHERE status = 'skipped'
       AND reason = 'no record URL on the list row'
    """,
    """
    UPDATE work_items
       SET status = 'needs_review'
     WHERE status = 'skipped'
    """,
)

#: Columns added in v6, as ``(table, column, declaration)``.
#:
#: ``CREATE TABLE IF NOT EXISTS`` never changes an existing table, so ``Database.migrate``
#: adds these with ``ALTER TABLE`` when the freshly created schema did not supply them.
V6_ADDED_COLUMNS = (
    ("work_item_refs", "state", "TEXT NOT NULL DEFAULT 'found'"),
    ("work_item_refs", "reason", "TEXT"),
    ("approved_deviation_refs", "state", "TEXT NOT NULL DEFAULT 'found'"),
    ("approved_deviation_refs", "reason", "TEXT"),
)

#: One-time v4 -> v5 backfill. Every statement is idempotent enough for a retry after a
#: crash before ``user_version`` is bumped. Snapshot timestamps use SQLite's UTC clock
#: because this script is executed before the Python repositories are built.
BACKFILL_APPROVED_HISTORY = (
    """
    INSERT OR IGNORE INTO approved_deviations
        (workflow, item_key, epoch, status, source, present, record_url, approved_at,
         reason, decided_at, decision_reason, snapshot_at)
    SELECT w.workflow, w.item_key, w.epoch, w.status, w.source, w.present,
           w.record_url, w.approved_at, w.reason, d.created_at, d.reason,
           strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
      FROM work_items w
      JOIN item_decisions d
        ON d.workflow = w.workflow AND d.item_key = w.item_key
     WHERE d.id = (
               SELECT MAX(m.id) FROM item_decisions m
                WHERE m.workflow = w.workflow AND m.item_key = w.item_key
           )
       AND d.decision = 'accept'
    """,
    """
    INSERT OR IGNORE INTO approved_deviation_fields
        (workflow, item_key, field_key, extracted, last_synced, proposed, applied,
         status, updated_at)
    SELECT f.workflow, f.item_key, f.field_key, f.extracted, f.last_synced,
           f.proposed, f.applied, f.status, f.updated_at
      FROM work_item_fields f
     WHERE EXISTS (
               SELECT 1 FROM approved_deviations a
                WHERE a.workflow = f.workflow AND a.item_key = f.item_key
           )
    """,
    """
    INSERT OR IGNORE INTO approved_deviation_attributes
        (workflow, item_key, name, value)
    SELECT a2.workflow, a2.item_key, a2.name, a2.value
      FROM work_item_attributes a2
     WHERE EXISTS (
               SELECT 1 FROM approved_deviations a
                WHERE a.workflow = a2.workflow AND a.item_key = a2.item_key
           )
    """,
    """
    INSERT OR IGNORE INTO approved_deviation_refs
        (workflow, item_key, kind, name, url)
    SELECT r.workflow, r.item_key, r.kind, r.name, r.url
      FROM work_item_refs r
     WHERE EXISTS (
               SELECT 1 FROM approved_deviations a
                WHERE a.workflow = r.workflow AND a.item_key = r.item_key
           )
    """,
    """
    INSERT INTO approved_deviation_edits
        (workflow, item_key, field_key, old_value, new_value, created_at)
    SELECT e.workflow, e.item_key, e.field_key, e.old_value, e.new_value, e.created_at
      FROM work_item_edits e
     WHERE EXISTS (
               SELECT 1 FROM approved_deviations a
                WHERE a.workflow = e.workflow AND a.item_key = e.item_key
           )
       AND NOT EXISTS (
               SELECT 1 FROM approved_deviation_edits x
                WHERE x.workflow = e.workflow
                  AND x.item_key = e.item_key
                  AND x.field_key = e.field_key
                  AND x.created_at = e.created_at
                  AND COALESCE(x.old_value, '') = COALESCE(e.old_value, '')
                  AND COALESCE(x.new_value, '') = COALESCE(e.new_value, '')
           )
    """,
)
