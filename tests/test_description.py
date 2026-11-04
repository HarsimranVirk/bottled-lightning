"""Description parsing tests, including the bare-``EMI-`` trap."""

from __future__ import annotations

import unittest

from app.deviations.extractors.common import parse_description_fields as legacy_parse
from app.workflows.deviations_z02.description import (
    clean_description,
    parse_description_fields,
)

DESCRIPTION = """\
Property Value (in Rs)- 45,00,000
Loan Amount (in Rs)- 25,50,000
Tenure (in months)- 240
EMI- 22,500
EMIs & other fixed pmts inc HFFC Loan- 23,100
"""


class DescriptionTests(unittest.TestCase):
    """Description parsing for both real shapes, including the EMI trap."""
    def test_parses_all_four_fields(self) -> None:
        """The verbose shape yields all four catalogue values."""
        self.assertEqual(
            parse_description_fields(DESCRIPTION),
            {
                "property_value": "45,00,000",
                "loan_amount": "25,50,000",
                "tenure": "240",
                "emi_incl_hffc": "23,100",
            },
        )

    def test_bare_emi_line_is_never_captured(self) -> None:
        """The pre-calculated EMI line must not become emi_incl_hffc."""
        self.assertEqual(
            parse_description_fields(DESCRIPTION)["emi_incl_hffc"], "23,100"
        )

    def test_alternate_emi_shape(self) -> None:
        """The shorter EMI wording is still recognised."""
        parsed = parse_description_fields("EMIs & other HFFC Loan- 18,000\n")
        self.assertEqual(parsed["emi_incl_hffc"], "18,000")

    def test_alternate_property_value_shape(self) -> None:
        """A more recently seen property-value wording parses."""
        parsed = parse_description_fields("New PP - 3840000\n")
        self.assertEqual(parsed["property_value"], "3840000")

    def test_alternate_property_value_ignores_percentage(self) -> None:
        """A percentage on that line is not mistaken for an amount."""
        parsed = parse_description_fields("New PP - 50%\n")
        self.assertIsNone(parsed["property_value"])

    def test_primary_property_value_pattern_wins(self) -> None:
        """When several labels match, the primary label takes precedence."""
        parsed = parse_description_fields("New PP - 38,40,000\nProperty Value - 45,00,000\n")
        self.assertEqual(parsed["property_value"], "45,00,000")

    def test_missing_fields_are_none(self) -> None:
        """Absent values are None, never empty strings."""
        self.assertEqual(
            parse_description_fields("Just some text\n"),
            {
                "property_value": None,
                "loan_amount": None,
                "tenure": None,
                "emi_incl_hffc": None,
            },
        )

    def test_legacy_shape_still_uses_emi_key(self) -> None:
        """The legacy extractor contract keeps its emi key."""
        parsed = legacy_parse(DESCRIPTION)
        self.assertEqual(parsed["emi"], "23,100")
        self.assertEqual(parsed["loan_amount"], "25,50,000")

    def test_compact_parameter_block(self) -> None:
        """The LA/PP/EMI compact shape parses into the catalogue keys."""
        text = (
            "Old Paramaters\n"
            "LA-13,00,000\n"
            "PP-22,50,000\n"
            "LTV-57.78%\n"
            "EMI-16,663\n"
            "EMIs & other fixed pmts inc HFFC Loan-16,256\n"
        )
        parsed = parse_description_fields(text)
        self.assertEqual(parsed["loan_amount"], "13,00,000")
        self.assertEqual(parsed["property_value"], "22,50,000")
        self.assertEqual(parsed["emi_incl_hffc"], "16,256")

    def test_compact_emi_line_is_not_the_precalculated_emi(self) -> None:
        """In the compact shape, only the EMIs & line is captured."""
        text = "EMI-16,663\nEMIs & other fixed pmts inc HFFC Loan-16,256\n"
        self.assertEqual(
            parse_description_fields(text)["emi_incl_hffc"], "16,256"
        )

    def test_percentage_values_are_not_amounts(self) -> None:
        """A percentage alone never becomes a property value."""
        parsed = parse_description_fields("New PP - 50%\n")
        self.assertIsNone(parsed["property_value"])

    def test_clean_description_drops_chrome(self) -> None:
        """Lightning's Help/Edit chrome is stripped from the body."""
        raw = (
            "Help Loan Deviation Description\n"
            "Loan Amount- 1\n"
            "Edit Loan Deviation Description\n"
        )
        self.assertEqual(clean_description(raw), "Loan Amount- 1")


if __name__ == "__main__":
    unittest.main()
