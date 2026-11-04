"""API services, DTO aliasing and the route table (no HTTP client needed)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.api.app import create_app
from app.api.errors import ApiError
from app.api.schemas import (
    ItemRowView,
    JobLogsView,
    JobsPageView,
    QueueView,
    SessionView,
    SyncView,
)
from app.api.services import WorkItemService, workflow_view
from app.config import Settings
from app.core.list_view import ListRow
from app.core.models import utcnow
from app.core.registry import WorkflowRegistry
from app.core.repo.decisions import DecisionRepository
from app.core.repo.edits import EditRepository
from app.core.repo.jobs import JobRepository
from app.core.status import WorkItemStatus
from app.core.workflow import Workflow
from app.workflows.deviations_z02 import build_workflow
from app.workflows.deviations_z02.adapters import build_adapters
from tests.support import DbTestCase

WORKFLOW = "deviations_z02"
KEY = "Deviation-03112026-486382"


def settings_for(root: Path) -> Settings:
    """Settings pointing at a temp data dir (only paths matter here)."""
    return Settings(
        org_base="https://example",
        data_dir=root,
        db_path=root / "app.db",
        workers=3,
        refresh_interval_s=30.0,
        request_timeout_ms=1000,
        login_wait_s=1,
        headless=True,
        update_policy="auto",
        deviations_z02_list_url="https://example/list",
        deviations_z02_pattern=r"Deviation-\d+-\d+",
    )


class ApiTestCase(DbTestCase):
    def build(
        self, *, paused: bool = False
    ) -> tuple[WorkItemService, WorkflowRegistry, Workflow, JobRepository, EditRepository]:
        deps = self.deps()
        workflow = build_workflow(
            settings_for(self.tmp_path),
            deps,
            build_adapters("https://example", 1000),
        )
        registry = WorkflowRegistry()
        registry.register(workflow)
        jobs = JobRepository(self.db)
        edits = EditRepository(self.db)
        service = WorkItemService(
            registry,
            deps.items,
            deps.fields,
            deps.attributes,
            deps.refs,
            edits,
            DecisionRepository(self.db),
            jobs,
            deps.events,
            lambda: paused,
        )
        return service, registry, workflow, jobs, edits

    def make_ready_item(self) -> Workflow:
        _service, _registry, workflow, _jobs, _edits = self.build()
        deps = self.deps()
        deps.items.create_present(
            WORKFLOW,
            ListRow(key=KEY, href=f"/lightning/r/a2f/{KEY}/view", columns={}, approved_at="4/11"),
            utcnow(),
        )
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.EXTRACTING)
        deps.items.transition(WORKFLOW, KEY, WorkItemStatus.READY, extracted_at=utcnow())
        deps.fields.set_extracted(WORKFLOW, KEY, {"loan_amount": "1300000", "tenure": "240"})
        return workflow


class ServiceTests(ApiTestCase):
    def test_workflow_view_uses_camel_case_aliases(self) -> None:
        _service, _registry, workflow, _jobs, _edits = self.build()
        payload = workflow_view(workflow).model_dump(by_alias=True)
        self.assertIn("listUrl", payload)
        field = payload["fields"][0]
        self.assertIn("valueType", field)
        self.assertEqual(field["required"], False)

    def test_list_items_includes_every_catalogue_field(self) -> None:
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        page = service.list_items(WORKFLOW)
        self.assertEqual(page.total, 1)
        row = page.rows[0]
        self.assertEqual(set(row.fields), {"loan_amount", "property_value", "tenure", "emi_incl_hffc"})
        self.assertEqual(row.fields["loan_amount"].extracted, "1300000")
        self.assertIsNone(row.fields["property_value"].extracted)

    def test_patch_normalises_and_moves_to_editing(self) -> None:
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        detail = service.patch_fields(WORKFLOW, KEY, {"loan_amount": "25,50,000"})
        self.assertEqual(detail.fields["loan_amount"].proposed, "2550000")
        self.assertEqual(detail.status, "editing")

    def test_patch_rejects_unparseable_values(self) -> None:
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        with self.assertRaises(ApiError) as caught:
            service.patch_fields(WORKFLOW, KEY, {"loan_amount": "not money"})
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.code, "invalid_value")

    def test_patch_rejects_unknown_fields(self) -> None:
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        with self.assertRaises(ApiError) as caught:
            service.patch_fields(WORKFLOW, KEY, {"nope": "1"})
        self.assertEqual(caught.exception.code, "unknown_field")

    def test_patch_requires_an_editable_status(self) -> None:
        service, _registry, _workflow, _jobs, _edits = self.build()
        deps = self.deps()
        deps.items.create_present(
            WORKFLOW,
            ListRow(key=KEY, href=f"/lightning/r/a2f/{KEY}/view", columns={}, approved_at=None),
            utcnow(),
        )
        with self.assertRaises(ApiError) as caught:
            service.patch_fields(WORKFLOW, KEY, {"tenure": "240"})
        self.assertEqual(caught.exception.status_code, 409)

    def test_patch_recovers_a_needs_review_item(self) -> None:
        """A failed submission can be corrected: needs_review -> ready -> editing."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        self.deps().items.transition(WORKFLOW, KEY, WorkItemStatus.NEEDS_REVIEW)
        detail = service.patch_fields(WORKFLOW, KEY, {"tenure": "240"})
        self.assertEqual(detail.status, "editing")
        self.assertEqual(detail.fields["tenure"].proposed, "240")

    def test_discard_returns_to_ready(self) -> None:
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        service.patch_fields(WORKFLOW, KEY, {"tenure": "300"})
        detail = service.discard_fields(WORKFLOW, KEY)
        self.assertEqual(detail.status, "ready")
        self.assertIsNone(detail.fields["tenure"].proposed)

    def test_accept_records_a_reversible_decision(self) -> None:
        """Accept is local and leaves the pipeline status alone (FR-10.2)."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()

        detail = service.decide(WORKFLOW, KEY, "accept")
        decision = detail.decision
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.decision, "accept")
        self.assertEqual(detail.status, "ready")
        self.assertEqual(len(detail.decisions), 1)

        accepted = service.list_items(WORKFLOW, decision="accept")
        self.assertEqual(accepted.total, 1)
        row_decision = accepted.rows[0].decision
        self.assertIsNotNone(row_decision)
        assert row_decision is not None
        self.assertEqual(row_decision.decision, "accept")

        undone = service.undo_decision(WORKFLOW, KEY)
        self.assertIsNone(undone.decision)
        # The undone decision stays in the audit trail; only PENDING is hidden.
        self.assertEqual([row.decision for row in undone.decisions], ["accept"])
        self.assertEqual(service.list_items(WORKFLOW, decision="accept").total, 0)
        self.assertEqual(service.list_items(WORKFLOW, decision="undecided").total, 1)

    def test_reject_keeps_the_reason(self) -> None:
        """A reject note is stored and visible on the decision."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        detail = service.decide(WORKFLOW, KEY, "reject", "  EMI does not match  ")
        decision = detail.decision
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.decision, "reject")
        self.assertEqual(decision.reason, "EMI does not match")
        self.assertEqual(service.list_items(WORKFLOW, decision="reject").total, 1)
        self.assertEqual(service.list_items(WORKFLOW, decision="undecided").total, 0)

    def test_decide_rejects_unknown_and_pending_kinds(self) -> None:
        """Only accept/reject are decisions; pending is the internal undo marker."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        for value in ("maybe", "pending"):
            with self.assertRaises(ApiError) as caught:
                service.decide(WORKFLOW, KEY, value)
            self.assertEqual(caught.exception.code, "invalid_decision")

    def test_decide_requires_a_decidable_status(self) -> None:
        """An in-flight item cannot be accepted or rejected."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        self.deps().items.transition(WORKFLOW, KEY, WorkItemStatus.SUBMITTING)
        with self.assertRaises(ApiError) as caught:
            service.decide(WORKFLOW, KEY, "accept")
        self.assertEqual(caught.exception.status_code, 409)

    def test_undo_without_a_decision_conflicts(self) -> None:
        """Undo is explicit: there is nothing to undo on an undecided item."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        with self.assertRaises(ApiError) as caught:
            service.undo_decision(WORKFLOW, KEY)
        self.assertEqual(caught.exception.code, "no_decision")

    def test_list_filters_by_several_statuses(self) -> None:
        """The deck asks for ready/editing/needs_review in one request."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        page = service.list_items(WORKFLOW, statuses=["ready", "needs_review"])
        self.assertEqual(page.total, 1)
        self.assertEqual(service.list_items(WORKFLOW, statuses=["present"]).total, 0)

    def test_list_rejects_an_unknown_decision_filter(self) -> None:
        """A bad filter is a 422, not silently ignored."""
        service, _registry, _workflow, _jobs, _edits = self.build()
        with self.assertRaises(ApiError) as caught:
            service.list_items(WORKFLOW, decision="maybe")
        self.assertEqual(caught.exception.code, "invalid_decision")

    def test_submit_requires_a_proposal(self) -> None:
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        with self.assertRaises(ApiError) as caught:
            service.submit(WORKFLOW, KEY)
        self.assertEqual(caught.exception.code, "nothing_to_submit")

    def test_submit_enqueues_one_job_and_marks_submitting(self) -> None:
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        service.patch_fields(WORKFLOW, KEY, {"tenure": "300"})
        job = service.submit(WORKFLOW, KEY)
        self.assertEqual(job.kind, "submit")
        self.assertEqual(job.status, "queued")
        item = self.deps().items.require(WORKFLOW, KEY)
        self.assertIs(item.status, WorkItemStatus.SUBMITTING)

        with self.assertRaises(ApiError) as caught:
            service.submit(WORKFLOW, KEY)
        self.assertEqual(caught.exception.status_code, 409)

    def test_submit_is_blocked_while_paused(self) -> None:
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build(paused=True)
        service.patch_fields(WORKFLOW, KEY, {"tenure": "300"})
        with self.assertRaises(ApiError) as caught:
            service.submit(WORKFLOW, KEY)
        self.assertEqual(caught.exception.code, "login_required")

    def test_unknown_workflow_and_item_are_404(self) -> None:
        service, _registry, _workflow, _jobs, _edits = self.build()
        with self.assertRaises(ApiError) as caught:
            service.list_items("nope")
        self.assertEqual(caught.exception.status_code, 404)
        with self.assertRaises(ApiError) as caught_item:
            service.get_item(WORKFLOW, "nope")
        self.assertEqual(caught_item.exception.status_code, 404)

    def test_invalid_status_filter_is_422(self) -> None:
        service, _registry, _workflow, _jobs, _edits = self.build()
        with self.assertRaises(ApiError) as caught:
            service.list_items(WORKFLOW, statuses=["bogus"])
        self.assertEqual(caught.exception.status_code, 422)


class _FakeAdmin:
    """AdminPort stub: the API tests only need the read shapes."""

    def session(self) -> SessionView:
        return SessionView(state="valid", paused=False, cookies=34, saved_at=None, last_event=None)

    def login(self) -> SessionView:
        return self.session()

    def logout(self) -> None:
        return None

    def latest_sync(self, workflow: str) -> SyncView | None:
        return SyncView(
            workflow=workflow,
            captured_at=datetime.now(UTC),
            header_total=7,
            rows_read=7,
            valid=True,
            warning=None,
            added=0,
            updated=7,
            closed=0,
        )

    def request_sync(self, workflow: str) -> None:
        return None

    def queue(self) -> QueueView:
        return QueueView(concurrency=3, in_flight=0, paused=False, counts={"queued": 1})

    def set_concurrency(self, concurrency: int) -> QueueView:
        return self.queue()

    def jobs(
        self,
        workflow: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        phase: str | None = None,
        item: str | None = None,
        job_id: str | None = None,
        error: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        duration_min_ms: int | None = None,
        duration_max_ms: int | None = None,
        sort: str = "id",
        order: str = "desc",
        limit: int = 25,
        offset: int = 0,
    ) -> JobsPageView:
        return JobsPageView(count=0, total=0, rows=[])

    def job_logs(self, job_id: int) -> JobLogsView:
        raise ApiError(404, "unknown job", "unknown_job")

    def cancel_job(self, job_id: int) -> None:
        raise ApiError(409, "not queued", "job_not_queued")


class RouteTests(ApiTestCase):
    def test_route_table_matches_the_api_document(self) -> None:
        service, registry, _workflow, _jobs, _edits = self.build()
        app = create_app(registry, service, _FakeAdmin())
        paths = app.openapi().get("paths", {})
        for expected in [
            ("GET", "/api/workflows"),
            ("GET", "/api/deviations"),
            ("GET", "/api/deviations/{key}"),
            ("PATCH", "/api/deviations/{key}/field-values"),
            ("DELETE", "/api/deviations/{key}/field-values"),
            ("POST", "/api/deviations/{key}/jobs"),
            ("GET", "/api/sessions"),
            ("POST", "/api/sessions"),
            ("DELETE", "/api/sessions"),
            ("GET", "/api/syncs"),
            ("POST", "/api/syncs"),
            ("GET", "/api/jobs"),
            ("GET", "/api/jobs/{job_id}"),
            ("DELETE", "/api/jobs/{job_id}"),
            ("GET", "/api/workers"),
            ("PATCH", "/api/workers"),
            ("GET", "/api/updates"),
        ]:
            method, path = expected
            self.assertIn(path, paths, path)
            self.assertIn(method.lower(), {m.lower() for m in paths[path]}, path)

    def test_legacy_alias_routes_are_gone(self) -> None:
        service, registry, _workflow, _jobs, _edits = self.build()
        app = create_app(registry, service, _FakeAdmin())
        paths = set(app.openapi().get("paths", {}))
        self.assertNotIn("/api/views", paths)
        self.assertNotIn("/api/views/{view_id}/run", paths)
        self.assertNotIn("/api/deviations/run", paths)
        self.assertNotIn("/api/deviations/sync", paths)

    def test_item_row_serialises_camel_case(self) -> None:
        row = ItemRowView(
            key="K",
            status="ready",
            present=True,
            epoch=1,
            record_url=None,
            approved_at=None,
            reason=None,
            fields={},
            active_job=None,
        )
        payload = row.model_dump(by_alias=True)
        self.assertIn("recordUrl", payload)
        self.assertIn("activeJob", payload)


if __name__ == "__main__":
    unittest.main()
