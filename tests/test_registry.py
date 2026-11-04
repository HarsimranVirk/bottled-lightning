"""The workflow seam: registration and a fake workflow needing no core change."""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from app.config import Settings
from app.core.errors import UnknownWorkflow
from app.core.field import EditableField, FieldTarget, ValueType
from app.core.list_view import ListRow, ListViewSpec
from app.core.models import WorkItem
from app.core.registry import WorkflowRegistry
from app.core.status import ExtractOutcome, SubmitOutcome, WorkItemStatus
from app.core.workflow import JobLogger, Workflow
from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabGroup
from app.workflows.deviations_z02 import WORKFLOW_NAME, build_workflow


class FakeExtraction:
    async def run(
        self, item: WorkItem, tabs: TabGroup, log: JobLogger
    ) -> ExtractOutcome:
        log(f"fake extraction {item.key}")
        return ExtractOutcome.EXTRACTED


class FakeSubmission:
    async def run(
        self, item: WorkItem, tabs: TabGroup, log: JobLogger
    ) -> SubmitOutcome:
        log(f"fake submission {item.key}")
        return SubmitOutcome.COMPLETED


def fake_workflow(name: str = "cancellations") -> Workflow:
    catalog: tuple[EditableField, ...] = (
        EditableField(
            key="reason",
            label="Reason",
            value_type=ValueType.TEXT,
            targets=(FieldTarget("case", "Reason"),),
        ),
    )

    def map_row(row: ListRow) -> Mapping[str, str]:
        return {"href": row.href}

    return Workflow(
        name=name,
        route=name,
        list_view=ListViewSpec(url="https://example/list", pattern=r"Case-\d+"),
        catalog=catalog,
        adapters=AdapterRegistry([]),
        extraction=FakeExtraction(),
        submission=FakeSubmission(),
        map_row=map_row,
        terminal_labels={WorkItemStatus.COMPLETED: "Approved"},
    )


def settings_for(path: Path) -> Settings:
    return Settings(
        org_base="https://example",
        data_dir=path,
        db_path=path / "app.db",
        workers=3,
        refresh_interval_s=30.0,
        request_timeout_ms=60_000,
        login_wait_s=600,
        headless=True,
        update_policy="auto",
        deviations_z02_list_url="https://example/list",
        deviations_z02_pattern=r"Deviation-\d+-\d+",
    )


class RegistryTests(unittest.TestCase):
    def test_accepts_a_second_workflow(self) -> None:
        registry = WorkflowRegistry()
        registry.register(fake_workflow())
        loaded = registry.get("cancellations")
        self.assertEqual(loaded.name, "cancellations")
        self.assertEqual(loaded.terminal_labels[WorkItemStatus.COMPLETED], "Approved")

    def test_unknown_workflow_raises(self) -> None:
        registry = WorkflowRegistry()
        with self.assertRaises(UnknownWorkflow):
            registry.get("nope")

    def test_two_workflows_coexist(self) -> None:
        registry = WorkflowRegistry()
        registry.register(fake_workflow())
        registry.register(fake_workflow("second"))
        self.assertEqual(registry.names(), ("cancellations", "second"))

    def test_deviations_workflow_is_registrable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = build_workflow(settings_for(Path(tmp)), AdapterRegistry([]))
        self.assertEqual(workflow.name, WORKFLOW_NAME)
        self.assertEqual(workflow.list_view.pattern, r"Deviation-\d+-\d+")
        self.assertEqual(
            [f.key for f in workflow.catalog],
            ["loan_amount", "property_value", "tenure", "emi_incl_hffc"],
        )
        self.assertEqual(
            workflow.terminal_labels[WorkItemStatus.COMPLETED], "Implemented"
        )

        registry = WorkflowRegistry()
        registry.register(workflow)
        self.assertEqual(registry.names(), (WORKFLOW_NAME,))


if __name__ == "__main__":
    unittest.main()
