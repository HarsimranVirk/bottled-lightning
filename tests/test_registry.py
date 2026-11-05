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
from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.status import ExtractOutcome, SubmitOutcome, WorkItemStatus
from app.core.workflow import JobLogger, Workflow, WorkflowDeps
from app.db.connection import Database
from app.salesforce.adapters import AdapterRegistry
from app.salesforce.tabs import TabProvider
from app.workflows.deviations_z02 import WORKFLOW_NAME, build_workflow


class FakeExtraction:
    """Stand-in extraction pipeline for the registry tests."""
    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> ExtractOutcome:
        """Stand-in pipeline that proves a workflow can be registered without core changes."""
        log(f"fake extraction {item.key}")
        return ExtractOutcome.EXTRACTED


class FakeSubmission:
    """Stand-in submission pipeline for the registry tests."""
    async def run(
        self, item: WorkItem, tabs: TabProvider, log: JobLogger
    ) -> SubmitOutcome:
        """Stand-in submission pipeline for the fake workflow."""
        log(f"fake submission {item.key}")
        return SubmitOutcome.COMPLETED


def fake_workflow(name: str = "cancellations") -> Workflow:
    """Minimal workflow used to prove the seam is workflow-agnostic."""
    catalog: tuple[EditableField, ...] = (
        EditableField(
            key="reason",
            label="Reason",
            value_type=ValueType.TEXT,
            targets=(FieldTarget("case", "Reason"),),
        ),
    )

    def map_row(row: ListRow) -> Mapping[str, str]:
        """No list columns are mapped for the fake workflow."""
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
    """Settings pointing at a temp data dir, for build_workflow tests."""
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
    """Workflow registration and lookup behaviour."""
    def test_accepts_a_second_workflow(self) -> None:
        """A second workflow registers and keeps its own labels."""
        registry = WorkflowRegistry()
        registry.register(fake_workflow())
        loaded = registry.get("cancellations")
        self.assertEqual(loaded.name, "cancellations")
        self.assertEqual(loaded.terminal_labels[WorkItemStatus.COMPLETED], "Approved")

    def test_unknown_workflow_raises(self) -> None:
        """Unknown names raise UnknownWorkflow rather than returning None."""
        registry = WorkflowRegistry()
        with self.assertRaises(UnknownWorkflow):
            registry.get("nope")

    def test_two_workflows_coexist(self) -> None:
        """Registration order is preserved and nothing is overwritten."""
        registry = WorkflowRegistry()
        registry.register(fake_workflow())
        registry.register(fake_workflow("second"))
        self.assertEqual(registry.names(), ("cancellations", "second"))

    def test_deviations_workflow_is_registrable(self) -> None:
        """The Z02 workflow builds from settings and exposes the expected route/catalogue."""
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "app.db")
            database.migrate()
            deps = WorkflowDeps(
                items=WorkItemRepository(database),
                fields=FieldValueRepository(database),
                attributes=AttributeRepository(database),
                refs=PageRefRepository(database),
                events=EventRepository(database),
            )
            workflow = build_workflow(settings_for(Path(tmp)), deps, AdapterRegistry([]))
            database.close()
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
