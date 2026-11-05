"""Field catalogue and SF object kinds for the Z02 loan-deviation workflow.

This is the only place where SF field labels appear. Adding an editable field is one
entry here; adapters derive their work from it (FR-4.3).
"""

from __future__ import annotations

from enum import StrEnum

from app.core.field import EditableField, FieldTarget, ValueType


class DeviationObject(StrEnum):
    """SF object kinds the Z02 workflow links to."""

    DEVIATION = "deviation"
    OPPORTUNITY = "opportunity"
    CL_CONTRACT = "cl_contract"
    COLLATERAL = "collateral"
    LMS2_CL_CONTRACT = "lms2_cl_contract"
    LMS2_COLLATERAL = "lms2_collateral"


# O-1 is resolved: every target below was confirmed against the live org. A field fans
# out to every object that must agree; the section names are the page areas the
# adapters scroll to (and disambiguate repeated labels on the LMS 2.0 forms).
FIELD_CATALOG: tuple[EditableField, ...] = (
    EditableField(
        key="loan_amount",
        label="Loan Amount",
        value_type=ValueType.AMOUNT,
        targets=(
            FieldTarget(
                DeviationObject.OPPORTUNITY, "Loan Amount", section="LOAN PARAMETERS"
            ),
            FieldTarget(
                DeviationObject.CL_CONTRACT, "Loan Amount", section="Contract"
            ),
            FieldTarget(
                DeviationObject.CL_CONTRACT, "Financed Amount", section="Funding"
            ),
            FieldTarget(
                DeviationObject.LMS2_CL_CONTRACT,
                "New value",
                section="Loan amount",
            ),
        ),
        source="loan_amount",
    ),
    EditableField(
        key="property_value",
        label="Property Value",
        value_type=ValueType.AMOUNT,
        targets=(
            FieldTarget(
                DeviationObject.OPPORTUNITY,
                "Property Value Ex. Reg & ST(Financeable)",
                section="LOAN PARAMETERS",
            ),
            FieldTarget(
                DeviationObject.COLLATERAL, "Property Value", section="Details"
            ),
            FieldTarget(
                DeviationObject.LMS2_COLLATERAL,
                "Property Value",
                section="Financials",
            ),
        ),
        source="property_value",
    ),
    EditableField(
        key="tenure",
        label="Tenure",
        value_type=ValueType.TENURE_MONTHS,
        targets=(
            FieldTarget(
                DeviationObject.OPPORTUNITY, "Tenure (Yrs)", section="LOAN PARAMETERS"
            ),
            FieldTarget(DeviationObject.CL_CONTRACT, "Term", section="Contract"),
            FieldTarget(
                DeviationObject.LMS2_CL_CONTRACT, "New value", section="Tenure"
            ),
        ),
        source="tenure",
    ),
    EditableField(
        key="emi_incl_hffc",
        label="EMI & other fixed payments incl. HFFC Loan",
        value_type=ValueType.AMOUNT,
        targets=(
            FieldTarget(
                DeviationObject.OPPORTUNITY,
                "EMIs & other fixed pmts inc HFFC Loan",
                section="BUDGET ANALYSIS & SAVINGS PATTERN",
            ),
        ),
        source="emi_incl_hffc",
    ),
)
