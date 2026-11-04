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
    url: str
    pattern: str


@dataclass(frozen=True, slots=True)
class ListRow:
    key: str
    href: str
    columns: Mapping[str, str]
    approved_at: str | None


@dataclass(frozen=True, slots=True)
class ListSample:
    captured_at: datetime
    header_total: int | None
    rows: tuple[ListRow, ...]

    @property
    def valid(self) -> bool:
        return is_valid_sample(self.header_total, self.rows)


def is_valid_sample(header_total: int | None, rows: Sequence[ListRow]) -> bool:
    return header_total is not None and header_total == len(rows)
