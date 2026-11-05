"""Description parsing tests, including the bare-``EMI-`` trap."""

from __future__ import annotations

import unittest

from app.deviations.extractors.common import parse_description_fields as legacy_parse
from app.workflows.deviations_z02.catalog import FIELD_CATALOG
from app.workflows.deviations_z02.description import (
    clean_description,
    parse_description_changes,
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

    def test_new_parameter_block_wins_over_old(self) -> None:
        """Only the New block is authoritative; the Old block is never parsed (FR-3.3)."""
        text = (
            "Old Paramaters\n"
            "LA-13,00,000\n"
            "PP-22,50,000\n"
            "LTV-57.78%\n"
            "EMI-16,663\n"
            "FOIR-40.64%\n"
            "EMIs & other fixed pmts inc HFFC Loan-16,256\n"
            "\n"
            "New Paramater\n"
            "LA-14,50,000\n"
            "PP-22,50,000\n"
            "LTV-64.44%\n"
            "EMI-18585\n"
            "FOIR-46.46\n"
            "EMIs & other fixed pmts inc HFFC Loan-18585\n"
        )
        parsed = parse_description_fields(text)
        self.assertEqual(parsed["loan_amount"], "14,50,000")
        self.assertEqual(parsed["property_value"], "22,50,000")
        self.assertEqual(parsed["emi_incl_hffc"], "18585")

    def test_verbose_new_block_aliases(self) -> None:
        """New loan amount / PP Value lines in the New block parse."""
        text = (
            "OLD PARAMETER\n"
            "Old loan amount - 6,00,000\n"
            "Tenure-10.0\n"
            "PP Value-₹12,00,000\n"
            "\n"
            "NEW PARAMETER\n"
            "New loan amount-5,00,000\n"
            "Tenure-10.0\n"
            "PP Value-₹10,00,000\n"
        )
        parsed = parse_description_fields(text)
        self.assertEqual(parsed["loan_amount"], "5,00,000")
        self.assertEqual(parsed["property_value"], "₹10,00,000")
        self.assertEqual(parsed["tenure"], "10.0")

    def test_new_parameter_section_does_not_fall_back_to_old(self) -> None:
        """A field absent from the New block stays empty; old values are not resurrected."""
        text = (
            "OLD PARAMETER:-\n"
            "Property Value Ex. Reg & ST(Financeable):- 22,00,000/-\n"
            "Loan Amount:- 9,80,000/-\n"
            "NEW PARAMETER:-\n"
            "Property Value Ex. Reg & ST(Financeable):- 13,00,000/-\n"
            "Loan Amount:- 9,80,000/-\n"
        )
        parsed = parse_description_fields(text)
        self.assertEqual(parsed["property_value"], "13,00,000/-")
        self.assertEqual(parsed["loan_amount"], "9,80,000/-")
        self.assertIsNone(parsed["tenure"])

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


class DescriptionChangesTests(unittest.TestCase):
    """Conservative prefill: only values that changed between Old and New."""

    OLD_NEW = (
        "Old Paramaters\n"
        "LA-13,00,000\n"
        "PP-22,50,000\n"
        "LTV-57.78%\n"
        "EMI-16,663\n"
        "FOIR-40.64%\n"
        "EMIs & other fixed pmts inc HFFC Loan-16,256\n"
        "\n"
        "New Paramater\n"
        "LA-14,50,000\n"
        "PP-22,50,000\n"
        "LTV-64.44%\n"
        "EMI-18585\n"
        "FOIR-46.46\n"
        "EMIs & other fixed pmts inc HFFC Loan-18585\n"
    )

    def test_only_changed_values_are_prefilled(self) -> None:
        """The real shape prefills loan amount and EMI, but not unchanged PP/tenure."""
        changes = parse_description_changes(self.OLD_NEW, FIELD_CATALOG)
        self.assertEqual(changes["loan_amount"], "14,50,000")
        self.assertEqual(changes["emi_incl_hffc"], "18585")
        self.assertIsNone(changes["property_value"])
        self.assertIsNone(changes["tenure"])

    def test_every_catalogue_key_is_present(self) -> None:
        """Unchanged fields are present as None so a previous prefill is cleared."""
        changes = parse_description_changes(self.OLD_NEW, FIELD_CATALOG)
        self.assertEqual(
            set(changes), {spec.key for spec in FIELD_CATALOG}
        )

    def test_single_block_is_never_prefilled(self) -> None:
        """Without an Old/New comparison there is not enough confidence."""
        text = (
            "Old Paramaters\n"
            "LA-13,00,000\n"
            "PP-22,50,000\n"
            "EMIs & other fixed pmts inc HFFC Loan-16,256\n"
        )
        changes = parse_description_changes(text, FIELD_CATALOG)
        self.assertTrue(all(value is None for value in changes.values()))

    def test_field_only_in_new_is_prefilled(self) -> None:
        """A New-only field is a proposed value; the Old block has nothing to compare."""
        text = (
            "OLD PARAMETER\n"
            "Loan Amount - 10,00,000\n"
            "\n"
            "NEW PARAMETER\n"
            "Loan Amount - 10,00,000\n"
            "Tenure - 240\n"
        )
        changes = parse_description_changes(text, FIELD_CATALOG)
        self.assertIsNone(changes["loan_amount"])
        self.assertEqual(changes["tenure"], "240")

    def test_field_only_in_old_is_not_prefilled(self) -> None:
        """A field the New block omits is not a proposed update."""
        text = (
            "OLD PARAMETER\n"
            "Loan Amount - 10,00,000\n"
            "Tenure - 240\n"
            "\n"
            "NEW PARAMETER\n"
            "Loan Amount - 12,00,000\n"
        )
        changes = parse_description_changes(text, FIELD_CATALOG)
        self.assertEqual(changes["loan_amount"], "12,00,000")
        self.assertIsNone(changes["tenure"])

    def test_formatting_equivalent_amounts_are_not_prefilled(self) -> None:
        """Indian grouping vs plain digits is not a value change."""
        text = (
            "OLD PARAMETER\n"
            "Loan Amount - 13,00,000\n"
            "\n"
            "NEW PARAMETER\n"
            "Loan Amount - 1300000\n"
        )
        self.assertIsNone(
            parse_description_changes(text, FIELD_CATALOG)["loan_amount"]
        )

    def test_trailing_slash_dash_is_ignored_for_equality(self) -> None:
        """``9,80,000/-`` and ``980000`` are the same amount."""
        text = (
            "OLD PARAMETER\n"
            "Loan Amount - 9,80,000/-\n"
            "\n"
            "NEW PARAMETER\n"
            "Loan Amount - 980000\n"
        )
        self.assertIsNone(
            parse_description_changes(text, FIELD_CATALOG)["loan_amount"]
        )

    def test_changed_amount_keeps_the_raw_new_text(self) -> None:
        """The parser suggests the raw New text and does not guess formatting."""
        text = (
            "OLD PARAMETER\n"
            "Loan Amount - 9,80,000/-\n"
            "\n"
            "NEW PARAMETER\n"
            "Loan Amount - 10,00,000/-\n"
        )
        self.assertEqual(
            parse_description_changes(text, FIELD_CATALOG)["loan_amount"],
            "10,00,000/-",
        )


if __name__ == "__main__":
    unittest.main()
