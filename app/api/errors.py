"""API boundary errors.

Handlers raise :class:`ApiError`; the app translates it into the JSON shape documented in
``docs/api-deviations.md`` (``{"detail": …}`` with an optional ``code``).
"""

from __future__ import annotations


class ApiError(Exception):
    """A request-level failure with an HTTP status and a machine-readable code."""

    def __init__(self, status_code: int, detail: str, code: str | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
