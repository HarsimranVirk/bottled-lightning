"""SF object adapters: one implementation per object kind, per workflow."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol, runtime_checkable

from playwright.async_api import Page

from app.core.errors import UnknownAdapter
from app.core.field import EditableField
from app.core.models import PageRef
from app.core.status import WriteOutcome

from .tabs import TabGroup


@runtime_checkable
class ObjectAdapter(Protocol):
    """Reads and writes the catalogue fields that live on one SF object."""

    kind: str

    async def open(self, tabs: TabGroup, ref: PageRef) -> Page: ...

    async def read(
        self, page: Page, fields: Sequence[EditableField]
    ) -> dict[str, str | None]: ...

    async def write(
        self, page: Page, values: Mapping[str, str]
    ) -> dict[str, WriteOutcome]: ...


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
