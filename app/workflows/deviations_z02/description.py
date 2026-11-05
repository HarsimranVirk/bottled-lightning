"""Loan-deviation description parsing.

Pure text handling, no browser. The bare ``EMI-`` line is the pre-calculated EMI and is
never captured (project hard-won rule); only the ``EMIs & other …`` line is.

Prefill is deliberately conservative. A value is only suggested when the description has
both an Old and a New parameter block and the New value differs from the Old value.
Without that comparison there is not enough confidence, so the field stays empty and the
operator supplies it. The parser never guesses units; it returns the raw New text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core.field import EditableField, ValueType, normalise

# Plain phrases only: add an alias by appending the label text, no regex needed. Labels
# are tried in order and the first matching line wins.
_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "property_value": ("Property Value", "New PP", "PP"),
    "loan_amount": ("New Loan Amount", "Loan Amount", "LA"),
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

_NEW_SECTION = re.compile(r"^\s*New\s+Param", re.IGNORECASE | re.MULTILINE)
_OLD_SECTION = re.compile(r"^\s*Old\s+Param", re.IGNORECASE | re.MULTILINE)

_DROP_LINES = (
    r"^\s*(Help |Edit |)?Loan Deviation Description\s*$",
    r"^\s* Help Loan Deviation Description\s*$",
)


def parse_description_fields(description: str) -> dict[str, str | None]:
    """
    Extract the raw catalogue-sourced values from one description block.

    This is the low-level parser used by both the old extraction path and the
    change-aware prefill. It returns the values from the New block when one exists,
    otherwise from the whole description. It does **not** decide whether a value
    changed; callers that need the conservative prefill use
    :func:`parse_description_changes`.

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
    _old, new = _sections(description)
    return _parse_block(new if new is not None else description)


def parse_description_changes(
    description: str, catalog: Sequence[EditableField]
) -> dict[str, str | None]:
    """
    Return only the values that changed between the Old and New parameter blocks.

    The rule is intentionally conservative to avoid false-positive prefills:

    * both blocks must exist — a single-block description yields no prefill at all;
    * a field present in both blocks is suggested only when the values differ;
    * a field present only in the New block is suggested (the Old block has no value
      to compare against);
    * a field present only in the Old block, or missing from both, stays ``None``.

    The result always contains every catalogue key, with ``None`` for unchanged or
    missing values. That matters because ``set_extracted`` writes the whole mapping:
    an unchanged field must clear a prefill from an earlier extraction, not keep it.

    Comparison is semantic when the values parse as the field's type (amounts ignore
    grouping/currency and a trailing ``/-``; tenure compares as months). If a value
    cannot be normalised, the parser falls back to trimmed string equality. The
    suggested value is always the raw New text; the parser never guesses units.
    """
    old_text, new_text = _sections(description)
    unchanged: dict[str, str | None] = {spec.key: None for spec in catalog}
    if old_text is None or new_text is None:
        return unchanged

    old_values = _parse_block(_strip_old_prefix(old_text))
    new_values = _parse_block(new_text)
    changes: dict[str, str | None] = {}
    for spec in catalog:
        new_value = new_values.get(spec.key)
        if new_value is None:
            changes[spec.key] = None
            continue
        old_value = old_values.get(spec.key)
        if old_value is None:
            changes[spec.key] = new_value
            continue
        changes[spec.key] = (
            None if _same_value(old_value, new_value, spec.value_type) else new_value
        )
    return changes


def _parse_block(text: str) -> dict[str, str | None]:
    """Extract the catalogue values from one block of text."""

    def grab(patterns: tuple[str, ...]) -> str | None:
        """First non-empty value across a set of label patterns."""
        for pattern in patterns:
            match = re.search(pattern, text)
            if match is None:
                continue
            value = match.group(1).strip()
            if value:
                return value
        return None

    return {key: grab(patterns) for key, patterns in _FIELD_PATTERNS.items()}


def _sections(description: str) -> tuple[str | None, str | None]:
    """
    Split a description into its Old and New parameter blocks.

    Returns ``(old_text, new_text)``; either side is ``None`` when its heading is absent.
    The blocks are delimited by the two headings, in whichever order they appear. A
    single-block description returns one side as ``None``, which makes the caller leave
    every field empty because there is no comparison to trust.
    """
    new = _NEW_SECTION.search(description)
    old = _OLD_SECTION.search(description)
    if new is None and old is None:
        return None, None
    if new is None:
        return (description[old.end() :] if old is not None else None), None
    if old is None:
        return None, description[new.end() :]
    if old.start() < new.start():
        return (
            description[old.end() : new.start()],
            description[new.end() :],
        )
    return (
        description[old.end() :],
        description[new.end() : old.start()],
    )


def _strip_old_prefix(text: str) -> str:
    """Remove a leading ``Old`` from each line so the shared label patterns match."""
    return "\n".join(
        re.sub(r"^\s*Old\s+", "", line, flags=re.IGNORECASE)
        for line in text.splitlines()
    )


def _same_value(old: str, new: str, value_type: ValueType) -> bool:
    """Whether two description values are equivalent for the field's type."""
    old_clean = _clean_for_compare(old)
    new_clean = _clean_for_compare(new)
    try:
        return normalise(old_clean, value_type) == normalise(new_clean, value_type)
    except ValueError:
        return old_clean == new_clean


def _clean_for_compare(value: str) -> str:
    """Trim a value and drop the common trailing ``/-`` decoration."""
    return value.strip().removesuffix("/-").strip()


def clean_description(raw: str) -> str:
    """Drop the Lightning chrome lines around the description body."""
    lines = raw.splitlines()
    kept = [
        line
        for line in lines
        if not any(re.match(pattern, line, re.IGNORECASE) for pattern in _DROP_LINES)
    ]
    return "\n".join(kept).strip()
