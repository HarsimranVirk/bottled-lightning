"""Bounded-wait helpers: real deadlines, no browser required (FR-7.12)."""

from __future__ import annotations

import asyncio
import time
import unittest

from app.utils.dom import (
    Deadline,
    clear_and_fill,
    click_first_visible,
    poll,
    settled_row_count,
)


class CountLocator:
    """A locator that reports a fixed element count and nothing else."""

    def __init__(self, count: int) -> None:
        """Store the count this locator always reports."""
        self._count = count

    async def count(self) -> int:
        """The configured number of matches."""
        return self._count

    def nth(self, index: int) -> CountLocator:
        """Unused by the row-count helper."""
        raise AssertionError("nth not expected")

    async def is_visible(self) -> bool:
        """Unused by the row-count helper."""
        raise AssertionError("is_visible not expected")

    async def click(self, *, timeout: float | None = None) -> None:
        """Unused by the row-count helper."""
        raise AssertionError("click not expected")

    async def fill(self, value: str, *, timeout: float | None = None) -> None:
        """Unused by the row-count helper."""
        raise AssertionError("fill not expected")

    async def input_value(self, *, timeout: float | None = None) -> str:
        """Unused by the row-count helper."""
        raise AssertionError("input_value not expected")


class BlockingClickLocator:
    """A visible locator whose click blocks far longer than the budget."""

    def __init__(self, click_s: float) -> None:
        """Store how long a click pretends to take."""
        self._click_s = click_s
        self.clicks = 0

    async def count(self) -> int:
        """One match."""
        return 1

    def nth(self, index: int) -> BlockingClickLocator:
        """The only match."""
        return self

    async def is_visible(self) -> bool:
        """Always visible."""
        return True

    async def click(self, *, timeout: float | None = None) -> None:
        """Block like a real action that never becomes clickable."""
        self.clicks += 1
        await asyncio.sleep(self._click_s)

    async def fill(self, value: str, *, timeout: float | None = None) -> None:
        """Unused by the click test."""
        raise AssertionError("fill not expected")

    async def input_value(self, *, timeout: float | None = None) -> str:
        """Unused by the click test."""
        raise AssertionError("input_value not expected")


class SlowFillLocator:
    """An input whose fill blocks, to prove the budget cancels it."""

    def __init__(self, delay_s: float) -> None:
        """Store the fill delay."""
        self._delay_s = delay_s
        self.value = ""

    async def count(self) -> int:
        """One match."""
        return 1

    def nth(self, index: int) -> SlowFillLocator:
        """The only match."""
        return self

    async def is_visible(self) -> bool:
        """Always visible."""
        return True

    async def click(self, *, timeout: float | None = None) -> None:
        """Unused by the fill test."""
        raise AssertionError("click not expected")

    async def fill(self, value: str, *, timeout: float | None = None) -> None:
        """Block for the configured delay, then store the value."""
        await asyncio.sleep(self._delay_s)
        self.value = value

    async def input_value(self, *, timeout: float | None = None) -> str:
        """Return the stored value."""
        return self.value


class DeadlineTests(unittest.TestCase):
    """The monotonic budget itself."""

    def test_expiry_and_remaining(self) -> None:
        """A short budget expires and never reports negative time."""
        deadline = Deadline(50)
        self.assertFalse(deadline.expired)
        self.assertGreater(deadline.remaining_ms(), 0)
        time.sleep(0.06)
        self.assertTrue(deadline.expired)
        self.assertEqual(deadline.remaining_ms(), 0)
        self.assertGreaterEqual(deadline.action_ms(), 1.0)


class BoundedWaitTests(unittest.IsolatedAsyncioTestCase):
    """Retrying helpers stop at the real deadline, not a nominal tick count."""

    async def test_poll_cancels_a_slow_predicate(self) -> None:
        """A predicate that never returns is cancelled at the budget, not retried."""

        async def slow_check() -> bool:
            await asyncio.sleep(0.5)
            return False

        started = time.monotonic()
        result = await poll(slow_check, timeout_ms=100, interval_ms=10)
        elapsed = time.monotonic() - started

        self.assertFalse(result)
        self.assertLess(elapsed, 0.3)

    async def test_click_first_visible_stops_at_the_budget(self) -> None:
        """A visible-but-blocking click cannot turn a 100 ms wait into seconds."""
        locator = BlockingClickLocator(click_s=5.0)

        started = time.monotonic()
        clicked = await click_first_visible(locator, timeout_ms=100)
        elapsed = time.monotonic() - started

        self.assertFalse(clicked)
        self.assertEqual(locator.clicks, 1)
        self.assertLess(elapsed, 0.5)

    async def test_clear_and_fill_stops_at_the_budget(self) -> None:
        """A blocked fill raises TimeoutError after the budget, not seconds later."""
        locator = SlowFillLocator(delay_s=5.0)

        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            await clear_and_fill(locator, "120", timeout_ms=100)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)


class SettledRowCountTests(unittest.IsolatedAsyncioTestCase):
    """An empty related list must be proven, never inferred from a timeout."""

    async def test_rows_win(self) -> None:
        """Rows rendered → the count is returned even if the empty marker exists."""
        count = await settled_row_count(
            CountLocator(2), CountLocator(1), timeout_ms=200
        )
        self.assertEqual(count, 2)

    async def test_positive_empty_state(self) -> None:
        """Salesforce's own "no items" text makes zero rows a real answer."""
        count = await settled_row_count(
            CountLocator(0), CountLocator(1), timeout_ms=200
        )
        self.assertEqual(count, 0)

    async def test_nothing_rendered_stays_unresolved(self) -> None:
        """Neither rows nor an empty marker → None, not zero."""
        started = time.monotonic()
        count = await settled_row_count(
            CountLocator(0), CountLocator(0), timeout_ms=100
        )
        elapsed = time.monotonic() - started

        self.assertIsNone(count)
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
