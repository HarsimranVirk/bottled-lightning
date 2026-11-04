"""List-page helpers that are pure (no browser)."""

from __future__ import annotations

import unittest

from app.core.list_view import ListRow, is_valid_sample
from app.salesforce.list_page import parse_item_total


class ItemTotalTests(unittest.TestCase):
    def test_reads_counts(self) -> None:
        self.assertEqual(parse_item_total("12 items • Updated 3 minutes ago"), 12)
        self.assertEqual(parse_item_total("1 item"), 1)
        self.assertEqual(parse_item_total("1,234 items"), 1234)
        self.assertEqual(parse_item_total("0 items"), 0)

    def test_missing_or_noisy_input(self) -> None:
        self.assertIsNone(parse_item_total("no rows here"))
        self.assertIsNone(parse_item_total(""))
        self.assertIsNone(parse_item_total("items"))


class ValidityRuleTests(unittest.TestCase):
    def _rows(self, count: int) -> tuple[ListRow, ...]:
        return tuple(
            ListRow(key=f"Deviation-{i}-1", href="", columns={}, approved_at=None)
            for i in range(count)
        )

    def test_matching_header_is_valid(self) -> None:
        self.assertTrue(is_valid_sample(3, self._rows(3)))
        self.assertTrue(is_valid_sample(0, self._rows(0)))

    def test_mismatch_or_missing_header_is_invalid(self) -> None:
        self.assertFalse(is_valid_sample(3, self._rows(2)))
        self.assertFalse(is_valid_sample(None, self._rows(3)))


if __name__ == "__main__":
    unittest.main()
