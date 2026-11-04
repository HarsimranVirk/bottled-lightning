"""List-page helpers that are pure (no browser)."""

from __future__ import annotations

import unittest

from app.core.list_view import ListRow, is_valid_sample
from app.salesforce.list_page import parse_item_total, resolve_href


class ItemTotalTests(unittest.TestCase):
    """Header-total parsing against real SF renderings."""
    def test_reads_counts(self) -> None:
        """Counts parse with separators and ignore the surrounding text."""
        self.assertEqual(parse_item_total("12 items • Updated 3 minutes ago"), 12)
        self.assertEqual(parse_item_total("1 item"), 1)
        self.assertEqual(parse_item_total("1,234 items"), 1234)
        self.assertEqual(parse_item_total("0 items"), 0)

    def test_missing_or_noisy_input(self) -> None:
        """Text without a count yields None, which invalidates the sample."""
        self.assertIsNone(parse_item_total("no rows here"))
        self.assertIsNone(parse_item_total(""))
        self.assertIsNone(parse_item_total("items"))


class RecordHrefTests(unittest.TestCase):
    """Record links are stored as absolute SF URLs, not app-relative paths."""

    LIST_URL = (
        "https://hffc.lightning.force.com/lightning/o/"
        "Consumer_Loan_Deviation__c/list?filterName=Z2_Loan_para_pricing1"
    )

    def test_root_relative_href_becomes_absolute(self) -> None:
        """Lightning renders '/lightning/r/…'; the UI must not open it on the app host."""
        self.assertEqual(
            resolve_href(self.LIST_URL, "/lightning/r/a2fS2000000fR5tIAE/view"),
            "https://hffc.lightning.force.com/lightning/r/a2fS2000000fR5tIAE/view",
        )

    def test_absolute_href_is_left_alone(self) -> None:
        """An already absolute record URL must not be prefixed twice."""
        href = "https://hffc.lightning.force.com/lightning/r/a2fS2000000fR5tIAE/view"
        self.assertEqual(resolve_href(self.LIST_URL, href), href)


class ValidityRuleTests(unittest.TestCase):
    """The single refresh-validity rule from FR-2.9."""
    def _rows(self, count: int) -> tuple[ListRow, ...]:
        """Build n synthetic rows for validity checks."""
        return tuple(
            ListRow(key=f"Deviation-{i}-1", href="", columns={}, approved_at=None)
            for i in range(count)
        )

    def test_matching_header_is_valid(self) -> None:
        """Header equal to parsed rows (including zero) is trustworthy."""
        self.assertTrue(is_valid_sample(3, self._rows(3)))
        self.assertTrue(is_valid_sample(0, self._rows(0)))

    def test_mismatch_or_missing_header_is_invalid(self) -> None:
        """A mismatch or absent header makes the refresh unusable."""
        self.assertFalse(is_valid_sample(3, self._rows(2)))
        self.assertFalse(is_valid_sample(None, self._rows(3)))


if __name__ == "__main__":
    unittest.main()
