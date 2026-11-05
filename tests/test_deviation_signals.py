"""The Implemented checkbox signal decision (no browser)."""

from __future__ import annotations

import unittest

from app.workflows.deviations_z02.adapters.deviation_record import (
    implemented_from_signals,
)


class ImplementedSignalTests(unittest.TestCase):
    """The tick is detected from any of the three LWC signals."""

    def test_checked_attribute_wins(self) -> None:
        """An empty `checked` attribute means true."""
        self.assertTrue(implemented_from_signals("", 0, 0))

    def test_check_icon_means_true(self) -> None:
        """The utility:check icon is a positive signal."""
        self.assertTrue(implemented_from_signals(None, 1, 0))

    def test_title_true_means_true(self) -> None:
        """An icon titled True is a positive signal."""
        self.assertTrue(implemented_from_signals(None, 0, 1))

    def test_the_steps_icon_is_false(self) -> None:
        """The unchecked render has no attribute, no check icon and title False."""
        self.assertFalse(implemented_from_signals(None, 0, 0))


if __name__ == "__main__":
    unittest.main()
