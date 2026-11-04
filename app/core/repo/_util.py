"""Small helpers shared by the repositories."""

from __future__ import annotations

from datetime import datetime

from app.core.models import from_iso


def opt_str(value: object) -> str | None:
    """Return a SQLite value as ``str``, preserving NULL."""
    if value is None:
        return None
    return str(value)


def opt_int(value: object) -> int | None:
    """Return a SQLite value as ``int``, preserving NULL."""
    if value is None:
        return None
    return int(str(value))


def opt_bool(value: object) -> bool:
    """Interpret a SQLite 0/1 column as ``bool``."""
    return bool(value)


def opt_time(value: object) -> datetime | None:
    """Parse an optional stored timestamp."""
    return from_iso(opt_str(value))
