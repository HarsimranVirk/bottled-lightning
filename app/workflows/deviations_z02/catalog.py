"""Field catalogue and SF object kinds for the Z02 loan-deviation workflow.

This is the only place where SF field labels appear. Adding an editable field is one
entry here; adapters derive their work from it (FR-4.3).
"""

from __future__ import annotations

from enum import StrEnum

from app.core.field import EditableField, FieldTarget, ValueType


class DeviationObject(StrEnum):
    DEVIATION = "deviation"
    OPPORTUNITY = "opportunity"
    CL_CONTRACT = "cl_contract"
    COLLATERAL = "collateral"
    LMS2_CL_CONTRACT = "lms2_cl_contract"
    LMS2_COLLATERAL = "lms2_collateral"


# NOTE: the FieldTargets below are placeholders pending open item O-1 (which SF object
# and field label each value is written to). Nothing else hard-codes these labels.
FIELD_CATALOG: tuple[EditableField, ...] = (
    EditableField(
        key="loan_amount",
        label="Loan Amount",
        value_type=ValueType.AMOUNT,
        targets=(FieldTarget(DeviationObject.CL_CONTRACT, "Loan Amount"),),
        source="loan_amount",
    ),
    EditableField(
        key="property_value",
        label="Property Value",
        value_type=ValueType.AMOUNT,
        targets=(FieldTarget(DeviationObject.COLLATERAL, "Property Value"),),
        source="property_value",
    ),
    EditableField(
        key="tenure",
        label="Tenure",
        value_type=ValueType.TENURE_MONTHS,
        targets=(FieldTarget(DeviationObject.CL_CONTRACT, "Tenure"),),
        source="tenure",
    ),
    EditableField(
        key="emi_incl_hffc",
        label="EMI & other fixed payments incl. HFFC Loan",
        value_type=ValueType.AMOUNT,
        targets=(FieldTarget(DeviationObject.CL_CONTRACT, "EMI"),),
        source="emi_incl_hffc",
    ),
)
