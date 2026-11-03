"""Extractor strategy protocol + concrete strategies."""

from .cl_contract import CLContractStrategy
from .collateral import CollateralStrategy
from .composite import CompositeExtractorStrategy
from .deviation_list_view import DeviationListViewStrategy
from .deviation_record_detail import DeviationRecordDetailStrategy
from .deviation_record_links import DeviationRecordLinksStrategy
from .lms2_cl_contract import LMS2ClContractStrategy
from .lms2_collateral import LMS2CollateralStrategy
from .opportunity_context import OpportunityContextStrategy
from .protocol import ExtractorStrategy, StrategyResult

__all__ = [
    "CLContractStrategy",
    "CollateralStrategy",
    "CompositeExtractorStrategy",
    "DeviationListViewStrategy",
    "DeviationRecordDetailStrategy",
    "DeviationRecordLinksStrategy",
    "ExtractorStrategy",
    "LMS2ClContractStrategy",
    "LMS2CollateralStrategy",
    "OpportunityContextStrategy",
    "StrategyResult",
]
