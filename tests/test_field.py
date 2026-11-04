"""Field model tests: canonical values and catalogue slicing."""

from __future__ import annotations

import unittest

from app.core.field import EditableField, FieldTarget, ValueType, fields_for, normalise
from app.workflows.deviations_z02.catalog import FIELD_CATALOG, DeviationObject


class NormaliseTests(unittest.TestCase):
    def test_amounts_collapse_to_one_form(self) -> None:
        for raw in ["2550000", "25,50,000", "₹ 25,50,000", " 25,50,000.00 ", "2550000.0"]:
            with self.subTest(raw=raw):
                self.assertEqual(normalise(raw, ValueType.AMOUNT), "2550000")

    def test_amount_keeps_fraction(self) -> None:
        self.assertEqual(normalise("25,50,000.50", ValueType.AMOUNT), "2550000.5")

    def test_amount_is_idempotent(self) -> None:
        once = normalise("25,50,000", ValueType.AMOUNT)
        self.assertEqual(normalise(once, ValueType.AMOUNT), once)

    def test_amount_rejects_garbage(self) -> None:
        with self.assertRaises(ValueError):
            normalise("not a number", ValueType.AMOUNT)
        with self.assertRaises(ValueError):
            normalise("", ValueType.AMOUNT)

    def test_tenure_months(self) -> None:
        self.assertEqual(normalise("240", ValueType.TENURE_MONTHS), "240")
        self.assertEqual(normalise(" 240 months ", ValueType.TENURE_MONTHS), "240")
        with self.assertRaises(ValueError):
            normalise("20 years", ValueType.TENURE_MONTHS)
        with self.assertRaises(ValueError):
            normalise("240.5", ValueType.TENURE_MONTHS)

    def test_text_collapses_whitespace(self) -> None:
        self.assertEqual(
            normalise("  Home   Loan (BT) ", ValueType.TEXT), "Home Loan (BT)"
        )


class FieldsForTests(unittest.TestCase):
    def test_slices_by_object(self) -> None:
        cl_keys = [f.key for f in fields_for(FIELD_CATALOG, DeviationObject.CL_CONTRACT)]
        self.assertEqual(cl_keys, ["loan_amount", "tenure", "emi_incl_hffc"])
        self.assertEqual(
            [f.key for f in fields_for(FIELD_CATALOG, DeviationObject.COLLATERAL)],
            ["property_value"],
        )
        self.assertEqual(fields_for(FIELD_CATALOG, DeviationObject.OPPORTUNITY), ())

    def test_multi_target_field_appears_in_every_slice(self) -> None:
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
        keys = [field.key for field in FIELD_CATALOG]
        self.assertEqual(len(keys), len(set(keys)))
        for field in FIELD_CATALOG:
            self.assertTrue(field.targets)


if __name__ == "__main__":
    unittest.main()
