"""Recursive JSON value type shared by loose payloads (updater, admin routes)."""

from __future__ import annotations

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
