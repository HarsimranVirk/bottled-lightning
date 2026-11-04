"""Small helpers shared by the repositories.

SQLite hands rows back as ``Any``, so these functions exist to turn a column
value into a concrete type at the one point where it enters a repository. They
are deliberately narrow: each one mirrors the column type it is used with, and
callers only pass columns of that type.
"""

from __future__ import annotations

from datetime import datetime

from app.core.models import from_iso


def opt_str(value: str | None) -> str | None:
    """Return a nullable TEXT column unchanged.

    Used for every nullable text column; SQLite returns ``None`` for NULL.
    """
    return value


def opt_int(value: int | None) -> int | None:
    """Return a nullable INTEGER column unchanged."""
    return value


def opt_bool(value: bool | None) -> bool:
    """Interpret a SQLite 0/1 INTEGER column as a bool (NULL becomes ``False``)."""
    return bool(value)


def opt_time(value: str | None) -> datetime | None:
    """Parse an optional ISO-8601 timestamp column into a datetime."""
    return from_iso(value)
