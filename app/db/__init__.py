"""Persistence primitives (connection, schema)."""

from __future__ import annotations

from .connection import Database
from .schema import SCHEMA, SCHEMA_VERSION

__all__ = ["SCHEMA", "SCHEMA_VERSION", "Database"]
