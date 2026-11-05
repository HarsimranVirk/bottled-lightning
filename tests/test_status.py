"""State machine tests (docs/class-design-deviations.md §5.1)."""

from __future__ import annotations

import unittest
from itertools import pairwise

from app.core.status import (
    TERMINAL_STATUSES,
    WorkItemStatus,
    can_transition,
)


class TransitionTests(unittest.TestCase):
    """Guards the item state machine: legal moves, dead ends, terminals."""
    def test_same_status_is_allowed(self) -> None:
        """Re-applying a status must be a no-op, so writes stay idempotent."""
        for status in WorkItemStatus:
            with self.subTest(status=status):
                self.assertTrue(can_transition(status, status))

    def test_happy_path(self) -> None:
        """Every step of the documented happy path is legal."""
        path = [
            WorkItemStatus.PRESENT,
            WorkItemStatus.EXTRACTING,
            WorkItemStatus.READY,
            WorkItemStatus.EDITING,
            WorkItemStatus.SUBMITTING,
            WorkItemStatus.APPLYING,
            WorkItemStatus.VALIDATING,
            WorkItemStatus.EXECUTING,
            WorkItemStatus.COMPLETED,
        ]
        for source, target in pairwise(path):
            with self.subTest(source=source, target=target):
                self.assertTrue(can_transition(source, target))

    def test_terminal_statuses(self) -> None:
        """Only completed/closed/skipped terminate an item."""
        self.assertEqual(
            TERMINAL_STATUSES,
            {
                WorkItemStatus.COMPLETED,
                WorkItemStatus.CLOSED,
                WorkItemStatus.SKIPPED,
            },
        )

    def test_execution_cannot_skip_validation(self) -> None:
        """The final action is unreachable except through validation (FR-6.5)."""
        self.assertFalse(can_transition(WorkItemStatus.APPLYING, WorkItemStatus.COMPLETED))
        self.assertFalse(
            can_transition(WorkItemStatus.VALIDATING, WorkItemStatus.COMPLETED)
        )
        self.assertFalse(can_transition(WorkItemStatus.READY, WorkItemStatus.COMPLETED))

    def test_terminal_states_reenter_only_via_new_epoch(self) -> None:
        """A closed item can only come back as present, starting a new epoch."""
        for status in TERMINAL_STATUSES:
            with self.subTest(status=status):
                self.assertTrue(can_transition(status, WorkItemStatus.PRESENT))
                self.assertFalse(can_transition(status, WorkItemStatus.READY))

    def test_needs_review_can_be_deferred_for_closure(self) -> None:
        """A disappeared needs_review item can still pass through absent_pending."""
        self.assertTrue(
            can_transition(WorkItemStatus.NEEDS_REVIEW, WorkItemStatus.ABSENT_PENDING)
        )

    def test_absent_pending_resolves_only_to_terminal(self) -> None:
        """A deferred closure resolves to a terminal state, never back to work."""
        self.assertTrue(
            can_transition(WorkItemStatus.ABSENT_PENDING, WorkItemStatus.COMPLETED)
        )
        self.assertTrue(
            can_transition(WorkItemStatus.ABSENT_PENDING, WorkItemStatus.CLOSED)
        )
        self.assertFalse(
            can_transition(WorkItemStatus.ABSENT_PENDING, WorkItemStatus.READY)
        )

    def test_no_dead_ends(self) -> None:
        """No status may be a trap: each can either move on or is terminal."""
        for status in WorkItemStatus:
            with self.subTest(status=status):
                if status in TERMINAL_STATUSES:
                    self.assertTrue(can_transition(status, WorkItemStatus.PRESENT))
                else:
                    self.assertTrue(
                        any(can_transition(status, other) for other in WorkItemStatus)
                    )


if __name__ == "__main__":
    unittest.main()
