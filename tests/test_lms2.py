"""LMS 2.0 row selection: product narrowing and the remaining ambiguity rule."""

from __future__ import annotations

import unittest

from app.workflows.deviations_z02.adapters.lms2 import (
    ApprovalAction,
    LmsRow,
    approval_action,
    approval_status,
    match_rows,
)


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


class ApprovalStatusTests(unittest.TestCase):
    """Only the header pill that names an approval state is selected."""

    def test_other_status_pills_are_ignored(self) -> None:
        texts = [
            "Pending Disbursal - 0.00%",
            "Current System Date : 04/11/2026",
            "Pending Approval",
        ]
        self.assertEqual(approval_status(texts), "Pending Approval")

    def test_no_matching_pill_returns_none(self) -> None:
        self.assertIsNone(approval_status(["Pending Disbursal", "Current System Date"]))

    def test_text_is_preserved_for_logging(self) -> None:
        self.assertEqual(approval_status(["  Rejected "]), "Rejected")

    def test_case_is_ignored(self) -> None:
        self.assertEqual(approval_status(["APPROVED"]), "APPROVED")

    def test_pending_wins_over_an_unrelated_approved_pill(self) -> None:
        self.assertEqual(
            approval_status(["Approved", "Pending Approval"]), "Pending Approval"
        )

    def test_leading_icon_is_ignored(self) -> None:
        self.assertEqual(approval_status(["✓ Approved"]), "✓ Approved")


class ApprovalActionTests(unittest.TestCase):
    """The LMS 2.0 contract state maps to one safe write decision."""

    def test_approved_contract_proceeds_without_clicking(self) -> None:
        self.assertIs(approval_action("Approved", True), ApprovalAction.PROCEED)

    def test_pending_contract_is_approved_when_the_control_is_there(self) -> None:
        self.assertIs(approval_action("Pending Approval", True), ApprovalAction.APPROVE)

    def test_pending_without_the_control_refuses(self) -> None:
        self.assertIs(approval_action("Pending Approval", False), ApprovalAction.REFUSE)

    def test_rejected_contract_is_refused(self) -> None:
        self.assertIs(approval_action("Rejected", True), ApprovalAction.REFUSE)

    def test_unknown_state_without_the_control_refuses(self) -> None:
        self.assertIs(approval_action(None, False), ApprovalAction.REFUSE)

    def test_unknown_state_with_the_control_is_treated_as_pending(self) -> None:
        self.assertIs(approval_action(None, True), ApprovalAction.APPROVE)

    def test_case_and_whitespace_do_not_matter(self) -> None:
        self.assertIs(
            approval_action("  pending APPROVAL ", True), ApprovalAction.APPROVE
        )

    def test_leading_icon_is_ignored(self) -> None:
        self.assertIs(approval_action("✓ Approved", False), ApprovalAction.PROCEED)


if __name__ == "__main__":
    unittest.main()
