"""List-view sampling: one refresh of a workflow's SF list page.

The validity rule (FR-2.9) lives here as a pure function so it is testable without a
browser: a refresh counts only when the "N items" header total was read and equals the
number of rows parsed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ListViewSpec:
    """
    Where a workflow's list view lives and what a row key looks like.

    ``url`` is the fully built Lightning list URL (including ``filterName``);
    ``pattern`` is the regex that finds the item key inside a row's text — a
    deviation number such as ``Deviation-28102026-484106``, for example. The
    pattern is shared by the list reader and the adapters so both agree on what an
    item key is.
    """

    url: str
    pattern: str


@dataclass(frozen=True, slots=True)
class ListRow:
    """
    One row read from a list view: key, record link and any list columns.

    ``href`` is the record path from the list (relative or absolute);
    ``approved_at`` is the Approval Date column when the printable view provided
    it. ``columns`` is reserved for list views that expose values directly.
    """

    key: str
    href: str
    columns: Mapping[str, str]
    approved_at: str | None


@dataclass(frozen=True, slots=True)
class ListSample:
    """
    One refresh of a list view, plus the evidence for whether to trust it.

    ``header_total`` is the "N items" text Salesforce renders; ``rows`` is what was
    actually parsed. Nothing may be closed or created unless ``valid`` is true —
    see FR-2.9 for why a single bad read must not close a deviation.

    Example (7 items, 7 rows parsed):
        sample.captured_at   # when the page was read
        sample.header_total  # 7
        len(sample.rows)     # 7
        sample.valid         # True
    """

    captured_at: datetime
    header_total: int | None
    rows: tuple[ListRow, ...]

    @property
    def valid(self) -> bool:
        """
        True when the header total was read and equals the parsed row count.

        Equivalent to :func:`is_valid_sample`; kept as a property so callers can
        branch on the sample itself.
        """
        return is_valid_sample(self.header_total, self.rows)


def is_valid_sample(header_total: int | None, rows: Sequence[ListRow]) -> bool:
    """
    The single validity rule (FR-2.9); pure, so it can be tested without a browser.

    A refresh counts only when the "N items" header was read *and* equals the
    number of rows parsed. A missing header or a mismatch means the read was
    untrustworthy (mid-render, blocked popup, virtualised table) and the caller must
    change no state.

    Examples:
        >>> is_valid_sample(12, rows_of(12))
        True
        >>> is_valid_sample(12, rows_of(11))
        False
        >>> is_valid_sample(None, rows_of(12))
        False
    """
    return header_total is not None and header_total == len(rows)
