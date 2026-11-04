"""Small helpers shared by the repositories."""

from __future__ import annotations

from datetime import datetime

from app.core.models import from_iso


def opt_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def opt_int(value: object) -> int | None:
    if value is None:
        return None
    return int(str(value))


def opt_bool(value: object) -> bool:
    return bool(value)


def opt_time(value: object) -> datetime | None:
    return from_iso(opt_str(value))
