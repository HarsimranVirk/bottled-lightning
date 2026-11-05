"""Shared base for deviation workflows: profile + registry + shared constants."""

from dataclasses import dataclass, field

from app.types import JsonValue
from app.workflows.deviations_z02.product_map import CL_CONTRACT_PRODUCT_MAP

# CL_CONTRACT_PRODUCT_MAP used to live here. The single source is now the v2 workflow
# package; it is re-exported so the legacy extractors keep working until Phase 9.

__all__ = ["CL_CONTRACT_PRODUCT_MAP", "WorkflowProfile", "get_profile", "list_profiles", "register"]


@dataclass(frozen=True)
class WorkflowProfile:
    name: str
    list_url: str
    filter_name: str
    pattern: str
    context: dict[str, JsonValue] = field(default_factory=dict)


_PROFILES: dict[str, WorkflowProfile] = {}


def register(profile: WorkflowProfile) -> None:
    _PROFILES[profile.name] = profile


def get_profile(name: str) -> WorkflowProfile | None:
    return _PROFILES.get(name)


def list_profiles() -> list[WorkflowProfile]:
    return list(_PROFILES.values())
