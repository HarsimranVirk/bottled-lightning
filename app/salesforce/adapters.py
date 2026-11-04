"""SF object adapters: one implementation per object kind, per workflow.

An adapter is responsible for exactly one SF object: discovering its link during
extraction (``discover``), and later reading/writing the catalogue fields on its record
page (``read`` / ``write``). It never decides retries or item status.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from playwright.async_api import Page

from app.core.errors import UnknownAdapter
from app.core.field import EditableField
from app.core.models import PageRef
from app.core.status import WriteOutcome

from .tabs import TabProvider


@dataclass(frozen=True, slots=True)
class DiscoveryContext:
    """What an adapter may need to find its object for one item."""

    item_key: str
    record_url: str
    opportunity_url: str | None = None
    product_type: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveredRef:
    """A link found during extraction; the pipeline turns it into a stored PageRef."""

    kind: str
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class Discovery:
    """What one adapter found: links, read-only values, editable values, or a skip."""

    refs: tuple[DiscoveredRef, ...] = ()
    attributes: Mapping[str, str | None] = field(default_factory=dict)
    fields: Mapping[str, str | None] = field(default_factory=dict)
    skip_reason: str | None = None


@runtime_checkable
class ObjectAdapter(Protocol):
    kind: str

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery: ...

    async def open(self, tabs: TabProvider, ref: PageRef) -> Page: ...

    async def read(
        self, page: Page, fields: Sequence[EditableField]
    ) -> dict[str, str | None]: ...

    async def write(
        self, page: Page, values: Mapping[str, str]
    ) -> dict[str, WriteOutcome]: ...


class AdapterBase:
    """Defaults for adapters that cannot yet do every job.

    ``read``/``write`` land with the submission pipeline (refactor Phase 6); until then
    they fail loudly rather than pretending to succeed.
    """

    kind: str = ""

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        raise NotImplementedError(f"{type(self).__name__}.discover")

    async def open(self, tabs: TabProvider, ref: PageRef) -> Page:
        return await tabs.new_page(ref.url)

    async def read(
        self, page: Page, fields: Sequence[EditableField]
    ) -> dict[str, str | None]:
        raise NotImplementedError(f"{type(self).__name__}.read (submission Phase 6)")

    async def write(
        self, page: Page, values: Mapping[str, str]
    ) -> dict[str, WriteOutcome]:
        raise NotImplementedError(f"{type(self).__name__}.write (submission Phase 6)")


class AdapterRegistry:
    def __init__(self, adapters: Iterable[ObjectAdapter]) -> None:
        self._adapters: dict[str, ObjectAdapter] = {
            adapter.kind: adapter for adapter in adapters
        }

    def get(self, kind: str) -> ObjectAdapter:
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise UnknownAdapter(kind)
        return adapter

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(self._adapters)
