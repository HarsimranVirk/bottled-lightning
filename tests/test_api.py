"""API services, DTO aliasing and the route table (no HTTP client needed)."""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.errors import ApiError
from app.api.schemas import (
    ItemRowView,
    JobLogsView,
    JobsPageView,
    NetworkView,
    QueueView,
    SessionView,
    SyncView,
    UpdateStatusView,
)
from app.api.services import WorkItemService, workflow_view
from app.config import Settings
from app.core.list_view import ListRow
from app.core.models import PageRef, utcnow
from app.core.registry import WorkflowRegistry
from app.core.repo.approved_history import ApprovedHistoryRepository
from app.core.repo.decisions import DecisionRepository
from app.core.repo.edits import EditRepository
from app.core.repo.jobs import JobRepository
from app.core.repo.refs import PageRefRepository
from app.core.status import WorkItemStatus
from app.core.workflow import Workflow
from app.devtools.db import DevDbService
from app.maintenance import PurgeService
from app.workflows.deviations_z02 import build_workflow
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
    )


class ApiTestCase(DbTestCase):
    def build(
        self, *, paused: bool = False
    ) -> tuple[WorkItemService, WorkflowRegistry, Workflow, JobRepository, EditRepository]:
        deps = self.deps()
        workflow = build_workflow(settings_for(self.tmp_path), deps)
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
            ApprovedHistoryRepository(self.db),
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

    def add_refs(self) -> None:
        """Give the fixture item all five object links."""
        PageRefRepository(self.db).replace(
            WORKFLOW,
            KEY,
            [
                PageRef(WORKFLOW, KEY, "opportunity", "Opportunity 1", "https://e/opp"),
                PageRef(WORKFLOW, KEY, "cl_contract", "LAI-00533155", "https://e/cl"),
                PageRef(WORKFLOW, KEY, "collateral", "CJID-0000280688", "https://e/coll"),
                PageRef(
                    WORKFLOW, KEY, "lms2_cl_contract", "LAI-00533155", "https://e/lm-cl"
                ),
                PageRef(
                    WORKFLOW, KEY, "lms2_collateral", "CJID-0000280688", "https://e/lm-coll"
                ),
            ],
        )


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

    def test_patch_empty_string_means_no_update(self) -> None:
        """Clearing an input discards the proposal instead of writing an empty value."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        service.patch_fields(WORKFLOW, KEY, {"loan_amount": "25,50,000"})
        detail = service.patch_fields(WORKFLOW, KEY, {"loan_amount": ""})
        self.assertIsNone(detail.fields["loan_amount"].proposed)

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

    def test_submit_ignores_empty_proposals(self) -> None:
        """An empty field is not a proposal, so there is nothing to submit."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        service.patch_fields(WORKFLOW, KEY, {"tenure": ""})
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

    def network(self) -> NetworkView:
        """Fixed LAN view for the network endpoint test."""
        return NetworkView(
            host="0.0.0.0",
            port=8765,
            lan_ip="192.168.1.42",
            lan_url="http://192.168.1.42:8765",
            local_url="http://127.0.0.1:8765",
            lan_enabled=True,
        )

    def update_status(self) -> UpdateStatusView:
        """No update pending in API tests."""
        return UpdateStatusView(status="up-to-date", update_available=False)

    def install_update(self, *, auto: bool = False) -> UpdateStatusView:
        """Same as the status; install behaviour is covered elsewhere."""
        return self.update_status()

    def jobs(
        self,
        workflow: str | None = None,
        kind: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        phase: Sequence[str] | None = None,
        status_text: str | None = None,
        kind_text: str | None = None,
        phase_text: str | None = None,
        item: str | None = None,
        item_in: Sequence[str] | None = None,
        job_id: str | None = None,
        id_in: Sequence[str] | None = None,
        error: str | None = None,
        error_in: Sequence[str] | None = None,
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


class HistoryServiceTests(ApiTestCase):
    """The History read model is independent from current item deletion."""

    def test_accept_writes_snapshot_and_history_survives_deletion(self) -> None:
        """History returns the accept snapshot even after work_items is emptied."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        service.decide(WORKFLOW, KEY, "accept")

        page = service.list_history(WORKFLOW)
        self.assertEqual(page.total, 1)
        self.assertEqual(page.rows[0].key, KEY)
        assert page.rows[0].decision is not None
        self.assertEqual(page.rows[0].decision.decision, "accept")

        conn = self.db.connect()
        for table in ("work_item_fields", "item_decisions", "work_items"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

        detail = service.get_history_item(WORKFLOW, KEY)
        self.assertEqual(detail.key, KEY)
        self.assertEqual(detail.status, "ready")
        self.assertEqual(detail.fields["loan_amount"].extracted, "1300000")

    def test_submit_refreshes_the_snapshot_with_edit_audit(self) -> None:
        """The edit audit written at submit time reaches the history detail."""
        self.make_ready_item()
        service, _registry, _workflow, _jobs, _edits = self.build()
        service.patch_fields(WORKFLOW, KEY, {"loan_amount": "25,50,000"})
        service.decide(WORKFLOW, KEY, "accept")
        service.submit(WORKFLOW, KEY)

        detail = service.get_history_item(WORKFLOW, KEY)
        self.assertEqual(detail.status, "submitting")
        self.assertEqual(len(detail.edits), 1)
        self.assertEqual(detail.edits[0].new_value, "2550000")

    def test_history_endpoint_returns_snapshot(self) -> None:
        """The HTTP history routes return the same shapes as the current item routes."""
        self.make_ready_item()
        service, registry, _workflow, _jobs, _edits = self.build()
        service.decide(WORKFLOW, KEY, "accept")
        client = TestClient(create_app(registry, service, _FakeAdmin()))

        page = client.get(f"/api/deviations/history?key={KEY}")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json()["total"], 1)
        filtered = client.get(
            "/api/deviations/history?status=ready&field=loan_amount:1300000"
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 1)
        miss = client.get("/api/deviations/history?status=closed")
        self.assertEqual(miss.status_code, 200)
        self.assertEqual(miss.json()["total"], 0)
        invalid = client.get("/api/deviations/history?field=bad")
        self.assertEqual(invalid.status_code, 422)
        detail = client.get(f"/api/deviations/history/{KEY}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["decision"]["decision"], "accept")
        ready = client.get("/api/deviations?status=ready")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["total"], 1)
        closed = client.get("/api/deviations?status=closed")
        self.assertEqual(closed.json()["total"], 0)

    def test_history_rows_carry_refs_and_ref_filters(self) -> None:
        """The history page returns the five links and filters on their names."""
        self.make_ready_item()
        self.add_refs()
        service, registry, _workflow, _jobs, _edits = self.build()
        service.decide(WORKFLOW, KEY, "accept")
        client = TestClient(create_app(registry, service, _FakeAdmin()))

        page = client.get("/api/deviations/history", params={"key": KEY})
        self.assertEqual(page.status_code, 200)
        row = page.json()["rows"][0]
        self.assertEqual(
            [ref["kind"] for ref in row["refs"]],
            [
                "opportunity",
                "cl_contract",
                "collateral",
                "lms2_cl_contract",
                "lms2_collateral",
            ],
        )
        self.assertEqual(row["refs"][2]["name"], "CJID-0000280688")

        exact = client.get(
            "/api/deviations/history", params={"ref": "collateral:CJID-0000280688"}
        )
        self.assertEqual(exact.json()["total"], 1)
        contains = client.get(
            "/api/deviations/history", params={"ref_text": "opportunity:Opportunity"}
        )
        self.assertEqual(contains.json()["total"], 1)
        wrong_kind = client.get(
            "/api/deviations/history", params={"ref": "collateral:Opportunity 1"}
        )
        self.assertEqual(wrong_kind.json()["total"], 0)
        invalid = client.get("/api/deviations/history", params={"ref": "bad"})
        self.assertEqual(invalid.status_code, 422)

    def test_network_endpoint_reports_the_lan_url(self) -> None:
        """The home page reads the bind and LAN address from the API."""
        service, registry, _workflow, _jobs, _edits = self.build()
        client = TestClient(create_app(registry, service, _FakeAdmin()))

        response = client.get("/api/network")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["lanIp"], "192.168.1.42")
        self.assertEqual(body["lanUrl"], "http://192.168.1.42:8765")
        self.assertEqual(body["localUrl"], "http://127.0.0.1:8765")
        self.assertTrue(body["lanEnabled"])


class RouteTests(ApiTestCase):
    def test_route_table_matches_the_api_document(self) -> None:
        service, registry, _workflow, _jobs, _edits = self.build()
        app = create_app(registry, service, _FakeAdmin())
        paths = app.openapi().get("paths", {})
        for expected in [
            ("GET", "/api/workflows"),
            ("GET", "/api/deviations"),
            ("GET", "/api/deviations/history"),
            ("GET", "/api/deviations/history/{key}"),
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
            ("GET", "/api/network"),
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


class DevApiTests(ApiTestCase):
    """Dev DB explorer routes: hidden when disabled, read-only when enabled."""

    def _client(self, *, enabled: bool = True) -> TestClient:
        service, registry, _workflow, _jobs, _edits = self.build()
        dev = DevDbService(
            self.tmp_path / "test.db",
            enabled=enabled,
            allow_remote=True,
        )
        return TestClient(
            create_app(
                registry,
                service,
                _FakeAdmin(),
                dev,
                PurgeService(self.db),
            )
        )

    def test_disabled_hides_the_surface(self) -> None:
        response = self._client(enabled=False).get("/api/dev/db/tables")
        self.assertEqual(response.status_code, 404)

    def test_tables_and_query(self) -> None:
        self.make_ready_item()
        client = self._client()
        tables = client.get("/api/dev/db/tables")
        self.assertEqual(tables.status_code, 200)
        names = [table["name"] for table in tables.json()["tables"]]
        self.assertIn("work_items", names)
        self.assertNotIn("sessions", names)

        response = client.post(
            "/api/dev/db/queries",
            json={"sql": "SELECT item_key FROM work_items", "limit": 10},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["columns"], ["item_key"])
        self.assertEqual(body["rows"][0][0], KEY)

    def test_purge_dry_run_then_real(self) -> None:
        """The dev purge route previews and then deletes the same rows."""
        self.make_ready_item()
        conn = self.db.connect()
        conn.execute(
            "UPDATE work_items SET first_seen = ?, last_seen = ?",
            ["2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00"],
        )
        conn.commit()
        client = self._client()

        preview = client.post(
            "/api/dev/db/purges",
            json={"scope": "current", "dryRun": True},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertGreater(preview.json()["total"], 0)
        still_there = client.post(
            "/api/dev/db/queries",
            json={"sql": "SELECT COUNT(*) AS n FROM work_items", "limit": 10},
        )
        self.assertEqual(still_there.json()["rows"][0][0], 1)

        real = client.post(
            "/api/dev/db/purges",
            json={"scope": "current", "dryRun": False},
        )
        self.assertEqual(real.status_code, 200)
        self.assertEqual(real.json()["deleted"], preview.json()["deleted"])
        self.assertEqual(real.json()["dryRun"], False)

    def test_purge_is_hidden_when_disabled(self) -> None:
        """The purge endpoint follows the same dev/localhost guard."""
        response = self._client(enabled=False).post(
            "/api/dev/db/purges",
            json={"scope": "history", "dryRun": True},
        )
        self.assertEqual(response.status_code, 404)

    def test_sessions_query_is_rejected(self) -> None:
        response = self._client().post(
            "/api/dev/db/queries", json={"sql": "SELECT * FROM sessions"}
        )
        self.assertEqual(response.status_code, 422)

    def test_exports_are_files(self) -> None:
        self.make_ready_item()
        client = self._client()
        csv = client.post(
            "/api/dev/db/exports",
            json={"sql": "SELECT item_key FROM work_items", "format": "csv"},
        )
        self.assertEqual(csv.status_code, 200)
        self.assertIn("text/csv", csv.headers["content-type"])
        self.assertIn(KEY, csv.text)

        workbook = client.post(
            "/api/dev/db/exports",
            json={"sql": "SELECT item_key FROM work_items", "format": "xlsx"},
        )
        self.assertEqual(workbook.status_code, 200)
        self.assertIn("spreadsheetml", workbook.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
