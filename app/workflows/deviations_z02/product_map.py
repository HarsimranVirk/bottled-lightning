"""Opportunity product type → CL-contract product mapping (deviation Z02).

Reference data, shared by the CL-contract adapter and (until it is deleted) the legacy
extractor package, which imports this module so there is exactly one copy.
"""

from __future__ import annotations

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
