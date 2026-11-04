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
    def test_same_status_is_allowed(self) -> None:
        for status in WorkItemStatus:
            with self.subTest(status=status):
                self.assertTrue(can_transition(status, status))

    def test_happy_path(self) -> None:
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
        self.assertEqual(
            TERMINAL_STATUSES,
            {
                WorkItemStatus.COMPLETED,
                WorkItemStatus.CLOSED,
                WorkItemStatus.SKIPPED,
            },
        )

    def test_execution_cannot_skip_validation(self) -> None:
        self.assertFalse(can_transition(WorkItemStatus.APPLYING, WorkItemStatus.COMPLETED))
        self.assertFalse(
            can_transition(WorkItemStatus.VALIDATING, WorkItemStatus.COMPLETED)
        )
        self.assertFalse(can_transition(WorkItemStatus.READY, WorkItemStatus.COMPLETED))

    def test_terminal_states_reenter_only_via_new_epoch(self) -> None:
        for status in TERMINAL_STATUSES:
            with self.subTest(status=status):
                self.assertTrue(can_transition(status, WorkItemStatus.PRESENT))
                self.assertFalse(can_transition(status, WorkItemStatus.READY))

    def test_absent_pending_resolves_only_to_terminal(self) -> None:
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
