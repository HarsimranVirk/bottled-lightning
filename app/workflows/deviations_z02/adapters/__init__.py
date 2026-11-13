"""Z02 SF object adapters, one per object kind."""

from __future__ import annotations

from app.config import TimeoutPolicy
from app.salesforce.adapters import AdapterRegistry

from .cl_contract import ClContractAdapter
from .collateral import CollateralAdapter
from .deviation_record import DeviationRecordAdapter
from .lms2 import Lms2ClContractAdapter, Lms2CollateralAdapter
from .opportunity import OpportunityAdapter


def build_adapters(org_base: str, timeouts: TimeoutPolicy) -> AdapterRegistry:
    """Construct the six Z02 adapters on one live timeout policy."""
    return AdapterRegistry(
        [
            DeviationRecordAdapter(org_base, timeouts),
            OpportunityAdapter(org_base, timeouts),
            ClContractAdapter(org_base, timeouts),
            CollateralAdapter(org_base, timeouts),
            Lms2ClContractAdapter(org_base, timeouts),
            Lms2CollateralAdapter(org_base, timeouts),
        ]
    )
