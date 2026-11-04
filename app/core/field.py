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
    """
    How a field's text is parsed, canonicalised, compared and rendered.

    Storage stays TEXT so nothing SF shows is lost, but every comparison goes
    through :func:`normalise`, which makes ``25,50,000`` and ``2550000.00`` the same
    value.

    * ``AMOUNT`` — money with Indian digit grouping and an optional currency symbol
    * ``TENURE_MONTHS`` — whole months; stored in months (project convention)
    * ``TEXT`` — free text, whitespace collapsed
    """

    AMOUNT = "amount"
    TENURE_MONTHS = "months"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class FieldTarget:
    """
    One SF field that a value is written to.

    ``object_kind`` is a key in the workflow's ``AdapterRegistry`` (for Z02:
    ``cl_contract``, ``collateral``, …); ``label`` is the SF field label on that
    record. ``section`` disambiguates labels that repeat on one page (the LMS 2.0
    contract modification form has a ``New value`` input in both the loan-amount and
    tenure cards), and is also the page area the adapter scrolls to before editing.
    A field has several targets when the same value must agree across objects
    (FR-6.3).

    Example:
        FieldTarget("cl_contract", "Loan Amount", section="Contract")
        FieldTarget("lms2_cl_contract", "New value", section="Tenure")
    """

    object_kind: str
    label: str
    section: str | None = None


@dataclass(frozen=True, slots=True)
class EditableField:
    """
    Declarative definition of one editable value — metadata, not data.

    The catalogue is code: adding a field is one entry, and adapters derive what to
    read and write from ``targets``. ``required`` means "must be supplied before
    submit", not "extraction must find it"; parsing is best-effort, so an
    unparsed value is simply empty.

    Example:
        EditableField(
            key="tenure",
            label="Tenure",
            value_type=ValueType.TENURE_MONTHS,
            targets=(FieldTarget("cl_contract", "Tenure"),),
            source="tenure",
        )
    """

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
    """
    Canonicalise a raw value for storage, comparison and validation.

    Idempotent: ``normalise(normalise(x)) == normalise(x)``. Raises ``ValueError``
    when the text cannot be interpreted — that is what turns a bad operator edit
    into a validation error instead of a bad write.

    Examples:
        >>> normalise("25,50,000", ValueType.AMOUNT)
        '2550000'
        >>> normalise("₹ 25,50,000.00", ValueType.AMOUNT)
        '2550000'
        >>> normalise(" 240 months ", ValueType.TENURE_MONTHS)
        '240'
        >>> normalise("  Home   Loan (BT) ", ValueType.TEXT)
        'Home Loan (BT)'
        >>> normalise("abc", ValueType.AMOUNT)
        Traceback (most recent call last):
        ValueError: not an amount: 'abc'
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
    """
    Catalogue slice for one SF object kind, in catalogue order.

    A field appears in every slice whose object it targets, so a value that must
    agree across objects is handled by each adapter without extra wiring.

    Example:
        >>> [f.key for f in fields_for(FIELD_CATALOG, "cl_contract")]
        ['loan_amount', 'tenure', 'emi_incl_hffc']
        >>> [f.key for f in fields_for(FIELD_CATALOG, "collateral")]
        ['property_value']
    """
    return tuple(
        field
        for field in catalog
        if any(target.object_kind == kind for target in field.targets)
    )
