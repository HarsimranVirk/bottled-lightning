"""Process-wide logging setup.

The browser layer logs per-row diagnostics at DEBUG (detached links, non-data table rows,
pages that are still rendering). Those are intentionally quiet by default: the durable
signal for a bad sample is the ``sync_runs`` warning, not a log line. Set
``SF_LOG_LEVEL=DEBUG`` when diagnosing a live run.
"""

from __future__ import annotations

import logging
import os

_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def log_level_from_env() -> int:
    """Root level from ``SF_LOG_LEVEL`` (default INFO)."""
    return _LEVELS.get(os.environ.get("SF_LOG_LEVEL", "INFO").upper(), logging.INFO)


def configure_logging() -> None:
    """Configure root logging once, from ``SF_LOG_LEVEL`` (default INFO)."""
    logging.basicConfig(level=log_level_from_env(), format=_FORMAT)
