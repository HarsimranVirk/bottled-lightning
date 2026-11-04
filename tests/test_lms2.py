"""LMS 2.0 row selection: product narrowing and the remaining ambiguity rule."""

from __future__ import annotations

import unittest

from app.workflows.deviations_z02.adapters.lms2 import LmsRow, match_rows


def row(name: str, *cells: str) -> LmsRow:
    return LmsRow(data_id=f"id-{name}", name=name, cells=cells)


class MatchRowsTests(unittest.TestCase):
    def test_two_rows_narrow_to_the_target_product(self) -> None:
        rows = [
            row("LAI-1", "LAI-1", "Approved", "Home Loan", "Home Loan Resale"),
            row("LAI-2", "LAI-2", "Approved", "Commercial Loan", "Shop Loan"),
        ]
        matched = match_rows(rows, "Home Loan")
        self.assertEqual([item.name for item in matched], ["LAI-1"])

    def test_two_rows_with_the_same_product_stay_ambiguous(self) -> None:
        rows = [
            row("LAI-1", "LAI-1", "Approved", "Home Loan"),
            row("LAI-2", "LAI-2", "Approved", "Home Loan"),
        ]
        self.assertEqual(len(match_rows(rows, "Home Loan")), 2)

    def test_product_variant_does_not_match_the_base_product(self) -> None:
        rows = [row("LAI-1", "LAI-1", "Home Loan Resale")]
        self.assertEqual(match_rows(rows, "Home Loan"), [])

    def test_unknown_target_keeps_every_row(self) -> None:
        rows = [row("LAI-1", "LAI-1", "Home Loan"), row("LAI-2", "LAI-2", "Commercial Loan")]
        self.assertEqual(len(match_rows(rows, None)), 2)


if __name__ == "__main__":
    unittest.main()
