"""Deviation Z2 workflow (thin: profile + own updaters)."""

from ..deviations.base import WorkflowProfile, register
from ..deviations.extractors import *
from .pipeline import run as run_extraction

PROFILE = WorkflowProfile(
    name="Loan Deviations Z02",
    list_url="https://hffc.lightning.force.com/lightning/o/Consumer_Loan_Deviation__c/list?filterName=Z2_Loan_para_pricing1",
    filter_name="Z2_Loan_para_pricing1",
    pattern=r"Deviation-\d+-\d+",
)
register(PROFILE)

__all__ = ["PROFILE", "run_extraction"]
