"""Dev-only database explorer support: read-only queries and exports.

This module is deliberately defensive. ``data/app.db`` contains the Salesforce session
snapshot in the ``sessions`` table, so the explorer uses a separate read-only connection,
denies every write/DDL/ATTACH/PRAGMA action through SQLite's authorizer, and denies any
read of ``sessions``. It is enabled by default, hidden from the main UI and, by default,
only reachable from localhost; ``SF_DEV_TOOLS=0`` disables it.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook

#: A single scalar cell. SQLite returns ints/floats/strings/None; blobs become a
#: placeholder string so raw session material can never be dumped through this path.
type DevCell = str | int | float | None

_QUERY_TIMEOUT_S = 2.0
_PREVIEW_LIMIT_MAX = 5_000
_EXPORT_LIMIT_MAX = 100_000
_SESSIONS_TABLE = "sessions"
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

_DENIED_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_CREATE_VTABLE,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_DROP_VTABLE,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_REINDEX,
        sqlite3.SQLITE_ANALYZE,
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_SAVEPOINT,
    }
)
_DENIED_FUNCTIONS = frozenset(
    {"load_extension", "writefile", "readfile", "edit", "fts3_tokenizer"}
)


class DevQueryError(Exception):
    """A query was rejected or failed; the route maps it to a clean 4xx/422."""


@dataclass(frozen=True, slots=True)
class DevTable:
    """One table in the explorer list."""

    name: str
    """SQLite table name, e.g. ``work_items``; the sessions table is never listed."""

    rows: int
    """Row count at listing time, for the explorer's overview."""

    columns: tuple[str, ...]
    """Column names in declaration order."""


@dataclass(frozen=True, slots=True)
class DevQueryResult:
    """A bounded, read-only result set."""

    columns: tuple[str, ...]
    """Result column names in query order."""

    rows: tuple[tuple[DevCell, ...], ...]
    """Result rows as scalars; SQLite blobs become placeholders, never raw bytes."""

    truncated: bool
    """True when the statement produced more rows than the caller's limit."""

    duration_ms: int
    """Wall-clock milliseconds the statement took, bounded by the explorer's timeout."""


def _authorizer(
    action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None
) -> int:
    """Allow only reads, and never a read of the session snapshot table."""
    if action in _DENIED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ and (arg1 or "").lower() == _SESSIONS_TABLE:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "") in _DENIED_FUNCTIONS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _cell(value: str | float | bytes | None) -> DevCell:
    """Convert one SQLite value to a safe JSON cell."""
    if isinstance(value, bytes):
        return f"<blob {len(value)} bytes>"
    return value


class DevDbService:
    """Read-only table metadata, bounded queries and CSV/Excel exports."""

    def __init__(self, db_path: Path, *, enabled: bool, allow_remote: bool) -> None:
        """Bind the database path and the dev-tool access policy."""
        self._db_path = db_path
        self.enabled = enabled
        self.allow_remote = allow_remote

    def require_allowed(self, host: str | None) -> None:
        """
        Enforce the dev-only and localhost policy.

        Raises ``DevQueryError`` when the tool is disabled or the request did not come
        from localhost. Routes translate that into a 404 so a production instance does
        not advertise the surface.
        """
        if not self.enabled:
            raise DevQueryError("dev tools are disabled")
        if not self.allow_remote and (host or "") not in _LOCAL_HOSTS:
            raise DevQueryError("dev tools are limited to localhost")

    def tables(self) -> tuple[DevTable, ...]:
        """Every user table except the token-bearing ``sessions`` table."""
        connection = self._open_readonly()
        try:
            names = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                    "AND name != ? ORDER BY name",
                    [_SESSIONS_TABLE],
                ).fetchall()
            ]
            tables: list[DevTable] = []
            for name in names:
                count = connection.execute(
                    f'SELECT COUNT(*) FROM "{name}"'
                ).fetchone()
                columns = tuple(
                    str(row[1])
                    for row in connection.execute(
                        f'PRAGMA table_info("{name}")'
                    ).fetchall()
                )
                tables.append(
                    DevTable(
                        name=name,
                        rows=int(count[0]) if count is not None else 0,
                        columns=columns,
                    )
                )
            return tuple(tables)
        finally:
            connection.close()

    def query(self, sql: str, limit: int = 500) -> DevQueryResult:
        """Run one read-only statement and return at most ``limit`` rows."""
        bounded = max(1, min(limit, _PREVIEW_LIMIT_MAX))
        return self._execute(sql, bounded)

    def export_csv(self, sql: str, limit: int = _EXPORT_LIMIT_MAX) -> str:
        """Run the query and return a CSV document."""
        result = self._execute(sql, limit, reject_truncated=True)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(result.columns)
        writer.writerows(result.rows)
        return buffer.getvalue()

    def export_xlsx(self, sql: str, limit: int = _EXPORT_LIMIT_MAX) -> bytes:
        """Run the query and return a real Excel workbook."""
        result = self._execute(sql, limit, reject_truncated=True)
        workbook = Workbook()
        sheet = workbook.active
        if sheet is None:
            raise DevQueryError("could not create a worksheet")
        sheet.title = "Query"
        sheet.append(list(result.columns))
        for row in result.rows:
            sheet.append(list(row))
        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()

    def _open_readonly(self) -> sqlite3.Connection:
        """Open a read-only connection before the authorizer is installed."""
        connection = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        return connection

    def _execute(
        self, sql: str, limit: int, *, reject_truncated: bool = False
    ) -> DevQueryResult:
        """Execute one guarded statement and bound the result."""
        if not sql.strip():
            raise DevQueryError("SQL is empty")
        connection = self._open_readonly()
        deadline = time.monotonic() + _QUERY_TIMEOUT_S
        connection.set_authorizer(_authorizer)
        connection.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0, 1000
        )
        started = time.monotonic()
        try:
            cursor = connection.execute(sql)
            columns = tuple(str(desc[0]) for desc in (cursor.description or ()))
            raw = cursor.fetchmany(limit + 1)
            truncated = len(raw) > limit
            if truncated and reject_truncated:
                raise DevQueryError(
                    f"result exceeds the {limit:,}-row export limit; add a LIMIT"
                )
            rows = tuple(tuple(_cell(value) for value in row) for row in raw[:limit])
            return DevQueryResult(
                columns=columns,
                rows=rows,
                truncated=truncated,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except sqlite3.ProgrammingError as exc:
            raise DevQueryError(
                "only one read-only statement is allowed per query"
            ) from exc
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            if "interrupted" in message.lower():
                message = "query exceeded the time limit"
            raise DevQueryError(message) from exc
        finally:
            connection.close()
