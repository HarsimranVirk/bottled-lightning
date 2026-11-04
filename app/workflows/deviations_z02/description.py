"""Loan-deviation description parsing.

Pure text handling, no browser. The bare ``EMI-`` line is the pre-calculated EMI and is
never captured (project hard-won rule); only the ``EMIs & other …`` line is.
"""

from __future__ import annotations

import re

# Plain phrases only: add an alias by appending the label text, no regex needed. Labels
# are tried in order and the first matching line wins.
_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "property_value": ("Property Value", "New PP", "PP"),
    "loan_amount": ("Loan Amount","LA"),
    "tenure": ("Tenure",),
    "emi_incl_hffc": ("EMIs &", "EMI &"),
}


def _label_pattern(label: str) -> str:
    """Build the matcher for one label: ``<label> … - <value>`` on a single line.

    The label is escaped, so it is matched literally. Percentage values are ignored
    (``New PP - 50%`` is a ratio, not an amount).
    """
    return rf"(?mi)^\s*{re.escape(label)}[^-\n]*-\s*([^%\n]+?)\s*$"


_FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    key: tuple(_label_pattern(label) for label in labels)
    for key, labels in _FIELD_LABELS.items()
}

_DROP_LINES = (
    r"^\s*(Help |Edit |)?Loan Deviation Description\s*$",
    r"^\s* Help Loan Deviation Description\s*$",
)


def parse_description_fields(description: str) -> dict[str, str | None]:
    """
    Extract the catalogue-sourced values from a deviation description.

    Descriptions appear in two shapes, both handled by label aliases:

    * verbose — ``Property Value (in Rs)- 45,00,000``, ``Loan Amount …-``,
      ``Tenure …-``
    * compact — ``LA-13,00,000``, ``PP-22,50,000``, ``EMI-16,663``

    The bare ``EMI-`` line is the pre-calculated EMI and must never be captured;
    only ``EMIs & other …-`` is. Percentages are ignored (``New PP - 50%`` is a
    ratio, not an amount). Parsing is best-effort: a missing value is ``None``.

    Example (compact shape, two lines of text):
        LA-13,00,000
        PP-22,50,000

        -> {'loan_amount': '13,00,000', 'property_value': '22,50,000',
            'tenure': None, 'emi_incl_hffc': None}
    """

    def grab(patterns: tuple[str, ...]) -> str | None:
        """First non-empty value across a set of label patterns."""
        for pattern in patterns:
            match = re.search(pattern, description)
            if match is None:
                continue
            value = match.group(1).strip()
            if value:
                return value
        return None

    return {key: grab(patterns) for key, patterns in _FIELD_PATTERNS.items()}


def clean_description(raw: str) -> str:
    """Drop the Lightning chrome lines around the description body."""
    lines = raw.splitlines()
    kept = [
        line
        for line in lines
        if not any(re.match(pattern, line, re.IGNORECASE) for pattern in _DROP_LINES)
    ]
    return "\n".join(kept).strip()
