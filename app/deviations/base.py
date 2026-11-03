"""Shared base for deviation workflows: profile + registry + shared constants."""

from dataclasses import dataclass, field

from app.types import JsonValue

# Deviation-specific mapping: Opportunity product type -> CL contract product.
# Applies to all deviation classes (z01-z04); not used by cancellations.
CL_CONTRACT_PRODUCT_MAP: dict[str, str] = {
    "Combo Top-Up": "Top Up Loan",
    "Commercial Property Loan": "Commercial Loan",
    "Construction Finance Product": "Construction Finance",
    "HL-BT + Renovation Loan": "Home Loan",
    "HL-BT + SECO": "Home Loan",
    "Home Loan": "Home Loan",
    "Home Loan (BT)": "Home Loan",
    "Home Loan (BT) + Top Up": "Home Loan",
    "Home Loan (Resale)": "Home Loan",
    "LAP + Renovation": "Loan Against Property",
    "LAP + SECO": "Loan Against Property",
    "LAP-BT": "Loan Against Property",
    "LAP-BT + Renovation Loan": "Loan Against Property",
    "LAP-BT + SECO": "Loan Against Property",
    "LAP-BT + Top-Up": "Loan Against Property",
    "Lap- refinance": "Loan Against Property",
    "Loan Against Property (LAP)": "Loan Against Property",
    "Loan Against Property against commercial property": "Loan Against Property",
    "Loan for Repair / Renovation / Extension": "Home Loan",
    "Loyalty Top-Up": "Top Up Loan",
    "Own Plot + HL (SeCo)": "Home Loan",
    "Plot Loan": "Plot Loan",
    "Plot Loan (BT) + SECO": "Plot Loan",
    "Plot Loan + HL (SeCo)": "Home Loan",
    "Renovation": "Home Loan",
    "SeCo": "Home Loan",
    "Shop Loan (Resale)": "Commercial Loan",
    "Shop Loan - BT": "Commercial Loan",
}


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
