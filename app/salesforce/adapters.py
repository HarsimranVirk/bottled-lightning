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

from app.config import TimeoutPolicy
from app.core.errors import UnknownAdapter
from app.core.field import FieldTarget
from app.core.job_logger import JobLogger
from app.core.models import PageRef
from app.core.status import RefState, WriteOutcome

from .tabs import TabProvider


def describe_target(target: FieldTarget) -> str:
    """
    Human-readable target name for job logs.

    Returns ``Label [Section]`` when the target carries a section, otherwise ``Label``.
    Adapters use it so a log line names the exact field the operator will recognise.
    """
    if target.section:
        return f"{target.label} [{target.section}]"
    return target.label


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
    """Item key being extracted, e.g. ``Deviation-28102026-484106``; used for log lines."""

    record_url: str
    """Lightning URL of the deviation record, taken from the list row; every adapter
    starts its discovery from here."""

    opportunity_url: str | None = None
    """URL of the opportunity the record belongs to, once the opportunity adapter has
    resolved it; ``None`` before that step or when it failed."""

    product_type: str | None = None
    """Product type read from the opportunity, e.g. ``Home Loan (Resale)``; the CL-contract
    adapter needs it to pick the right form, so it is ``None`` until that step runs."""


@dataclass(frozen=True, slots=True)
class DiscoveredRef:
    """
    One SF object link, or the plain reason it could not be linked.

    ``state`` is what the pipeline stores on the item. ``FOUND`` carries a usable
    ``url`` and ``name``. ``ABSENT`` says the related list rendered and was positively
    empty, so the object does not exist for this item. ``UNRESOLVED`` says the lookup
    itself did not finish (page never opened, match ambiguous); it is the safe default
    because a failed fetch must never look like a genuine absence.

    Non-``FOUND`` refs carry empty ``name``/``url`` and a short ``reason`` written for
    the operator ("No collateral attached to this opportunity"). Exception text and
    timeouts belong in the job log, never in ``reason``.

    Example:
        DiscoveredRef("cl_contract", "LAI-1", "https://org/lightning/r/LAI/1/view")
        absent("collateral", "No collateral attached to this opportunity")
    """

    kind: str
    """Object kind this link is for, e.g. ``opportunity``; must be one of the workflow's
    declared ``RefKind`` values."""

    name: str = ""
    """The object's Salesforce identifier as displayed, e.g. ``LAI-00533155``; ``""`` when
    nothing was found."""

    url: str = ""
    """Absolute Lightning URL to open; ``""`` when ``state`` is not ``FOUND``."""

    state: RefState = RefState.FOUND
    """``FOUND``, ``ABSENT`` (positively no such object) or ``UNRESOLVED`` (the lookup did
    not finish); the pipeline stores it verbatim on the item."""

    reason: str | None = None
    """One operator-facing sentence when ``state`` is not ``FOUND``; exception text and
    timeouts belong in the job log, never here."""


def unresolved(kind: str, reason: str) -> DiscoveredRef:
    """
    A link extraction could not resolve, with the plain reason to show the operator.

    Adapters use this for a page that never opened, a list that never rendered, or a
    match they refuse to guess. The item needs review and the operator can retry.
    """
    return DiscoveredRef(kind=kind, state=RefState.UNRESOLVED, reason=reason)


def absent(kind: str, reason: str) -> DiscoveredRef:
    """
    A link that positively does not exist for this item.

    Only call this after Salesforce itself said the list is empty (its "no items"
    text or an empty shadow root). A timeout must stay ``UNRESOLVED``.
    """
    return DiscoveredRef(kind=kind, state=RefState.ABSENT, reason=reason)


@dataclass(frozen=True, slots=True)
class Discovery:
    """
    What one adapter found.

    Adapters contribute only their own slice: links (``refs``), read-only values
    (``attributes``) and catalogue values they are the source of (``fields``). The
    pipeline merges the slices and persists once. An adapter that owns a link kind
    returns exactly one ref for it, even when that ref is ``ABSENT``/``UNRESOLVED``;
    returning nothing leaves the pipeline to report the kind as unresolved.

    Example:
        Discovery(refs=(DiscoveredRef("cl_contract", "LAI-1", url),))
        Discovery(refs=(absent("cl_contract", "No CL contract for this product"),))
    """

    refs: tuple[DiscoveredRef, ...] = ()
    """Links this adapter owns, one per kind it is responsible for (including ``ABSENT``
    ones, so the pipeline never has to guess)."""

    attributes: Mapping[str, str | None] = field(default_factory=dict)
    """Read-only values found here, keyed by stored attribute name (e.g. ``description``);
    ``None`` records a value the page genuinely had nothing for."""

    fields: Mapping[str, str | None] = field(default_factory=dict)
    """Catalogue values this adapter is the source of, keyed by field key (e.g.
    ``tenure``); merged into the item's extracted values by the pipeline."""


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
    """Object kind this adapter serves, e.g. ``cl_contract``; must match a declared
    ``RefKind.kind`` and the kind on every ref, attribute and field it returns."""

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext, log: JobLogger
    ) -> Discovery:
        """Find this object for an item (extraction)."""
        ...

    async def open(self, tabs: TabProvider, ref: PageRef) -> Page:
        """Open this object's record page for reading or writing."""
        ...

    async def read(
        self, page: Page, targets: Sequence[FieldTarget], log: JobLogger
    ) -> dict[FieldTarget, str | None]:
        """Read the target values that live on this object, in canonical units."""
        ...

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str], log: JobLogger
    ) -> dict[FieldTarget, WriteOutcome]:
        """Write canonical values to their targets; returns per-target outcomes."""
        ...


class AdapterBase:
    """Defaults for adapters that cannot yet do every job.

    ``read``/``write`` land with the submission pipeline (refactor Phase 6); until then
    they fail loudly rather than pretending to succeed.

    The org base and the live timeout policy are stored once here, so every adapter
    reaches ``self._timeout_ms`` without knowing which profile is active.
    """

    kind: str = ""
    """Object kind served by this base adapter; subclasses override it with a declared
    ``RefKind.kind``."""

    def __init__(self, org_base: str, timeouts: TimeoutPolicy) -> None:
        """Store the org base and the policy every wait reads."""
        self._org_base = org_base
        self._timeouts = timeouts

    @property
    def _timeout_ms(self) -> int:
        """Per-action timeout in milliseconds, read live so a profile change applies to
        the next wait even inside a running job."""
        return self._timeouts.current().action_ms

    async def discover(
        self, tabs: TabProvider, context: DiscoveryContext, log: JobLogger
    ) -> Discovery:
        """Not implemented for base adapters."""
        raise NotImplementedError(f"{type(self).__name__}.discover")

    async def open(self, tabs: TabProvider, ref: PageRef) -> Page:
        """Open the ref's URL in a new tab."""
        return await tabs.new_page(ref.url)

    async def read(
        self, page: Page, targets: Sequence[FieldTarget], log: JobLogger
    ) -> dict[FieldTarget, str | None]:
        """Not implemented for base adapters."""
        raise NotImplementedError(f"{type(self).__name__}.read")

    async def write(
        self, page: Page, values: Mapping[FieldTarget, str], log: JobLogger
    ) -> dict[FieldTarget, WriteOutcome]:
        """Not implemented for base adapters."""
        raise NotImplementedError(f"{type(self).__name__}.write")


class AdapterRegistry:
    """
    Adapters by object kind for one workflow.

    Example:
        registry = build_adapters(settings.org_base, settings.timeouts)
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
