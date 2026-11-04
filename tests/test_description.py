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
    def test_parses_all_four_fields(self) -> None:
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
        self.assertEqual(
            parse_description_fields(DESCRIPTION)["emi_incl_hffc"], "23,100"
        )

    def test_alternate_emi_shape(self) -> None:
        parsed = parse_description_fields("EMIs & other HFFC Loan- 18,000\n")
        self.assertEqual(parsed["emi_incl_hffc"], "18,000")

    def test_missing_fields_are_none(self) -> None:
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
        parsed = legacy_parse(DESCRIPTION)
        self.assertEqual(parsed["emi"], "23,100")
        self.assertEqual(parsed["loan_amount"], "25,50,000")

    def test_clean_description_drops_chrome(self) -> None:
        raw = (
            "Help Loan Deviation Description\n"
            "Loan Amount- 1\n"
            "Edit Loan Deviation Description\n"
        )
        self.assertEqual(clean_description(raw), "Loan Amount- 1")


if __name__ == "__main__":
    unittest.main()
