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
from app.core.field import FieldTarget
from app.core.models import PageRef
from app.core.status import WriteOutcome

from .tabs import TabProvider


@dataclass(frozen=True, slots=True)
class DiscoveryContext:
    """
    What an adapter may need in order to find its object.

    Adapters are run in dependency order, and the context carries the results: the
    record URL comes from the list row, the opportunity URL from the record page,
    and the product type from the opportunity (the CL-contract match needs it).

    Example progression for one item:
        DiscoveryContext(item_key="Deviation-…", record_url="/lightning/r/a2f…/view")
        … opportunity_url="https://org/lightning/r/Opportunity/006…/view"
        … product_type="Home Loan (Resale)"
    """

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
    """
    What one adapter found, or why it stopped.

    Adapters contribute only their own slice: links (``refs``), read-only values
    (``attributes``), catalogue values they are the source of (``fields``), or a
    ``skip_reason`` such as an ambiguous match. The pipeline merges the slices and
    persists once.

    Example:
        Discovery(refs=(DiscoveredRef("cl_contract", "LAI-1", url),))
        Discovery(skip_reason="multiple matching CL contracts (2)")
    """

    refs: tuple[DiscoveredRef, ...] = ()
    attributes: Mapping[str, str | None] = field(default_factory=dict)
    fields: Mapping[str, str | None] = field(default_factory=dict)
    skip_reason: str | None = None


@runtime_checkable
class ObjectAdapter(Protocol):
    """
    One SF object kind: discovery, reading and writing its fields.

    ``discover`` runs during extraction and returns a slice (never persists).
    ``read``/``write`` operate on an already-open record page and are used by the
    submission pipeline. They take :class:`FieldTarget` values so the pipeline keeps
    field keys and the adapter keeps page/label knowledge. Adapters depend on
    ``TabProvider``, so pipelines can be tested without a browser.
    """

    kind: str

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        """Find this object for an item (extraction)."""
        ...

    async def open(self, tabs: TabProvider, ref: PageRef) -> Page:
        """Open this object's record page for reading or writing."""
        ...

    async def read(
        self, page: Page, targets: Sequence[FieldTarget]
    ) -> dict[FieldTarget, str | None]:
        """Read the target values that live on this object, in canonical units."""
        ...

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str]
    ) -> dict[FieldTarget, WriteOutcome]:
        """Write canonical values to their targets; returns per-target outcomes."""
        ...


class AdapterBase:
    """Defaults for adapters that cannot yet do every job.

    ``read``/``write`` land with the submission pipeline (refactor Phase 6); until then
    they fail loudly rather than pretending to succeed.
    """

    kind: str = ""

    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery:
        """Not implemented for base adapters."""
        raise NotImplementedError(f"{type(self).__name__}.discover")

    async def open(self, tabs: TabProvider, ref: PageRef) -> Page:
        """Open the ref's URL in a new tab."""
        return await tabs.new_page(ref.url)

    async def read(
        self, page: Page, targets: Sequence[FieldTarget]
    ) -> dict[FieldTarget, str | None]:
        """Not implemented for base adapters."""
        raise NotImplementedError(f"{type(self).__name__}.read")

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str]
    ) -> dict[FieldTarget, WriteOutcome]:
        """Not implemented for base adapters."""
        raise NotImplementedError(f"{type(self).__name__}.write")


class AdapterRegistry:
    """
    Adapters by object kind for one workflow.

    Example:
        registry = build_adapters(settings.org_base, settings.request_timeout_ms)
        adapter = registry.get("cl_contract")
    """

    def __init__(self, adapters: Iterable[ObjectAdapter]) -> None:
        """Index adapters by ``kind``."""
        self._adapters: dict[str, ObjectAdapter] = {
            adapter.kind: adapter for adapter in adapters
        }

    def get(self, kind: str) -> ObjectAdapter:
        """Adapter for an object kind or raise ``UnknownAdapter``."""
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise UnknownAdapter(kind)
        return adapter

    @property
    def kinds(self) -> tuple[str, ...]:
        """Registered object kinds."""
        return tuple(self._adapters)
