"""Z02 SF object adapters, one per object kind."""

from __future__ import annotations

from app.salesforce.adapters import AdapterRegistry

from .cl_contract import ClContractAdapter
from .collateral import CollateralAdapter
from .deviation_record import DeviationRecordAdapter
from .lms2 import Lms2ClContractAdapter, Lms2CollateralAdapter
from .opportunity import OpportunityAdapter


def build_adapters(org_base: str, timeout_ms: int) -> AdapterRegistry:
    """Construct the six Z02 adapters."""
    return AdapterRegistry(
        [
            DeviationRecordAdapter(org_base, timeout_ms),
            OpportunityAdapter(org_base, timeout_ms),
            ClContractAdapter(org_base, timeout_ms),
            CollateralAdapter(org_base, timeout_ms),
            Lms2ClContractAdapter(org_base, timeout_ms),
            Lms2CollateralAdapter(org_base, timeout_ms),
        ]
    )
