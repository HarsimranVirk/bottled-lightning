"""Deviation Z4 workflow (thin)."""

from app.deviations_z02.pipeline import run as run_extraction

from ..deviations.base import WorkflowProfile, register
from ..deviations.extractors import *

PROFILE = WorkflowProfile(
    name="Loan Deviations Z4",
    list_url="https://hffc.lightning.force.com/lightning/o/Consumer_Loan_Deviation__c/list?filterName=Z4_Loan_para_pricing1",
    filter_name="Z4_Loan_para_pricing1",
    pattern=r"Deviation-\d+-\d+",
)
register(PROFILE)

__all__ = ["PROFILE", "run_extraction"]
