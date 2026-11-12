"""Field model tests: canonical values and catalogue slicing."""

from __future__ import annotations

import unittest

from app.core.field import (
    EditableField,
    FieldTarget,
    ValueType,
    _normalize_number,
    fields_for,
    normalise,
)
from app.workflows.deviations_z02.catalog import FIELD_CATALOG, DeviationObject


class NormaliseTests(unittest.TestCase):
    """Canonicalisation rules for amounts, tenure and text."""
    def test_amounts_collapse_to_one_form(self) -> None:
        """Indian grouping, currency symbols and trailing zeros compare equal."""
        for raw in ["2550000", "25,50,000", "₹ 25,50,000", " 25,50,000.00 ", "2550000.0"]:
            with self.subTest(raw=raw):
                self.assertEqual(normalise(raw, ValueType.AMOUNT), "2550000")

    def test_amount_keeps_fraction(self) -> None:
        """A real fractional amount is preserved, not rounded away."""
        self.assertEqual(normalise("25,50,000.50", ValueType.AMOUNT), "2550000.5")

    def test_amount_is_idempotent(self) -> None:
        """Normalising twice changes nothing, which callers rely on."""
        once = normalise("25,50,000", ValueType.AMOUNT)
        self.assertEqual(normalise(once, ValueType.AMOUNT), once)

    def test_amount_rejects_garbage(self) -> None:
        """Unparseable money raises instead of writing a bad value."""
        with self.assertRaises(ValueError):
            normalise("not a number", ValueType.AMOUNT)
        with self.assertRaises(ValueError):
            normalise("", ValueType.AMOUNT)

    def test_tenure_months(self) -> None:
        """Tenure is stored as whole months, with units tolerated and fractions rejected."""
        self.assertEqual(normalise("240", ValueType.TENURE_MONTHS), "240")
        self.assertEqual(normalise(" 240 months ", ValueType.TENURE_MONTHS), "240")
        with self.assertRaises(ValueError):
            normalise("20 years", ValueType.TENURE_MONTHS)
        with self.assertRaises(ValueError):
            normalise("240.5", ValueType.TENURE_MONTHS)

    def test_text_collapses_whitespace(self) -> None:
        """Free text is trimmed and internal runs collapsed for comparison."""
        self.assertEqual(
            normalise("  Home   Loan (BT) ", ValueType.TEXT), "Home Loan (BT)"
        )


class NormalizeNumberTests(unittest.TestCase):
    """Operator-entered rate: trim, canonicalise the decimal, and enforce 0–100."""

    def test_trims_whitespace_and_canonicalises_the_decimal(self) -> None:
        """Whitespace and trailing zeros are dropped; the rate itself never changes."""
        self.assertEqual(_normalize_number(" 11.95 "), "11.95")
        self.assertEqual(_normalize_number(" 11.95% "), "11.95")
        self.assertEqual(_normalize_number(" 0.1195 "), "0.1195")
        self.assertEqual(_normalize_number("13.00"), "13")
        self.assertEqual(_normalize_number("013.0%"), "13")

    def test_percent_unit_is_ignored_for_comparison(self) -> None:
        """The Opportunity displays 11.95%; the canonical value is 11.95."""
        self.assertEqual(
            _normalize_number("11.95%"), _normalize_number("11.95")
        )

    def test_salesforce_two_decimal_display_matches_the_proposal(self) -> None:
        """A 13% proposal and the page's 13.00% read-back are the same rate."""
        self.assertEqual(_normalize_number("13.00%"), _normalize_number("13"))

    def test_accepts_inclusive_bounds(self) -> None:
        """Both 0 and 100 are valid rates, however they are written."""
        expected = {"0": "0", "0.00": "0", "100": "100", "100.00": "100"}
        for raw, canonical in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(_normalize_number(raw), canonical)

    def test_rejects_out_of_range(self) -> None:
        """A rate below 0 or above 100 is a validation error, not a clamp."""
        for raw in ("-0.01", "-1", "100.01", "101"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _normalize_number(raw)

    def test_rejects_non_numeric_and_empty(self) -> None:
        """Empty, garbage and non-finite values cannot become a rate."""
        for raw in ("", "   ", "abc", "NaN", "Infinity"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _normalize_number(raw)


class FieldsForTests(unittest.TestCase):
    """Catalogue slicing: which fields belong to which SF object."""
    def test_slices_by_object(self) -> None:
        """Each object receives exactly the fields it targets."""
        self.assertEqual(
            [f.key for f in fields_for(FIELD_CATALOG, DeviationObject.CL_CONTRACT)],
            ["loan_amount", "tenure"],
        )
        self.assertEqual(
            [f.key for f in fields_for(FIELD_CATALOG, DeviationObject.COLLATERAL)],
            ["property_value"],
        )
        self.assertEqual(
            [
                f.key
                for f in fields_for(FIELD_CATALOG, DeviationObject.OPPORTUNITY)
            ],
            ["loan_amount", "property_value", "tenure", "roi", "emi_incl_hffc"],
        )
        self.assertEqual(
            [
                f.key
                for f in fields_for(FIELD_CATALOG, DeviationObject.LMS2_COLLATERAL)
            ],
            ["property_value"],
        )
        self.assertEqual(
            [
                f.key
                for f in fields_for(FIELD_CATALOG, DeviationObject.LMS2_CL_CONTRACT)
            ],
            ["loan_amount", "tenure"],
        )

    def test_multi_target_field_appears_in_every_slice(self) -> None:
        """A value shared by two objects is handled by both adapters."""
        field = EditableField(
            key="shared",
            label="Shared",
            value_type=ValueType.AMOUNT,
            targets=(
                FieldTarget("cl_contract", "A"),
                FieldTarget("collateral", "B"),
            ),
        )
        self.assertIn(field, fields_for((field,), "cl_contract"))
        self.assertIn(field, fields_for((field,), "collateral"))

    def test_catalog_keys_are_unique_and_have_targets(self) -> None:
        """The catalogue cannot contain duplicates or unbound fields."""
        keys = [field.key for field in FIELD_CATALOG]
        self.assertEqual(len(keys), len(set(keys)))
        for field in FIELD_CATALOG:
            self.assertTrue(field.targets)

    def test_roi_is_opportunity_only_and_numeric(self) -> None:
        """ROI is written only on the Opportunity and uses the 0–100 rule."""
        field = next(field for field in FIELD_CATALOG if field.key == "roi")
        self.assertIs(field.value_type, ValueType.NUMBER)
        self.assertEqual(
            [target.object_kind for target in field.targets],
            [DeviationObject.OPPORTUNITY],
        )


if __name__ == "__main__":
    unittest.main()
