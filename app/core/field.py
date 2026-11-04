"""Field model: what an editable field is, where it lives in SF, and how to canonicalise it.

``EditableField`` / ``FIELD_CATALOG`` are metadata (code). ``FieldValue`` (models.py) is
the per-item data those definitions govern.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class ValueType(StrEnum):
    """How a field's text is parsed, canonicalised and compared."""

    AMOUNT = "amount"
    TENURE_MONTHS = "months"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class FieldTarget:
    """One SF field that a value is written to."""

    object_kind: str
    label: str


@dataclass(frozen=True, slots=True)
class EditableField:
    """One editable value: label, type, and the SF fields it is written to."""

    key: str
    label: str
    value_type: ValueType
    targets: tuple[FieldTarget, ...]
    #: Must be supplied by the operator before submit. Parsing is best-effort: a value
    #: that could not be extracted simply has no extracted value and is not an error.
    required: bool = False
    source: str | None = None


_AMOUNT_STRIP = re.compile(r"[,\s\u20b9$]")
_MONTHS = re.compile(r"^(\d+)\s*(?:months?|mon|mos?|m)?$", re.IGNORECASE)


def normalise(value: str, value_type: ValueType) -> str:
    """Canonical form used for storage, comparison and validation.

    Idempotent. Raises ``ValueError`` for input that cannot be interpreted.
    """
    match value_type:
        case ValueType.AMOUNT:
            return _normalise_amount(value)
        case ValueType.TENURE_MONTHS:
            return _normalise_months(value)
        case ValueType.TEXT:
            return _normalise_text(value)


def _normalise_amount(value: str) -> str:
    """Strip currency decoration and return a plain decimal string."""
    cleaned = _AMOUNT_STRIP.sub("", value)
    if not cleaned:
        raise ValueError("empty amount")
    try:
        number = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"not an amount: {value!r}")
    text = format(number.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _normalise_months(value: str) -> str:
    """Parse a tenure into whole months."""
    match = _MONTHS.match(value.strip())
    if match is None:
        raise ValueError(f"not a tenure in months: {value!r}")
    return str(int(match.group(1)))


def _normalise_text(value: str) -> str:
    """Trim and collapse internal whitespace."""
    return " ".join(value.split())


def fields_for(
    catalog: Sequence[EditableField], kind: str
) -> tuple[EditableField, ...]:
    """Catalogue slice for one SF object kind; catalogue order is preserved."""
    return tuple(
        field
        for field in catalog
        if any(target.object_kind == kind for target in field.targets)
    )
