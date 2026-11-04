"""Loan-deviation description parsing.

Pure text handling, no browser. The bare ``EMI-`` line is the pre-calculated EMI and is
never captured (project hard-won rule); only the ``EMIs & other …`` line is.
"""

from __future__ import annotations

import re

_FIELD_PATTERNS: dict[str, str] = {
    "property_value": r"(?m)^\s*Property Value[^-\n]*-\s?(.+)$",
    "loan_amount": r"(?m)^\s*Loan Amount[^-\n]*-\s?(.+)$",
    "tenure": r"(?m)^\s*Tenure[^-\n]*-\s?(.+)$",
    "emi_incl_hffc": r"(?m)^\s*EMIs?\s*&[^-\n]*-\s?(.+)$",
}

_DROP_LINES = (
    r"^\s*(Help |Edit |)?Loan Deviation Description\s*$",
    r"^\s* Help Loan Deviation Description\s*$",
)


def parse_description_fields(description: str) -> dict[str, str | None]:
    """Extract the catalogue-sourced values from a deviation description."""

    def grab(pattern: str) -> str | None:
        match = re.search(pattern, description)
        if match is None:
            return None
        value = match.group(1).strip()
        return value or None

    return {key: grab(pattern) for key, pattern in _FIELD_PATTERNS.items()}


def clean_description(raw: str) -> str:
    """Drop the Lightning chrome lines around the description body."""
    lines = raw.splitlines()
    kept = [
        line
        for line in lines
        if not any(re.match(pattern, line, re.IGNORECASE) for pattern in _DROP_LINES)
    ]
    return "\n".join(kept).strip()
