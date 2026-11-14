"""Manual LMS 2.0 contract links and the automatic approval pipeline."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from playwright.async_api import Page

from app.api.app import create_app
from app.api.errors import ApiError
from app.api.services import WorkItemService
from app.config import Settings, TimeoutPolicy
from app.core.list_view import ListRow
from app.core.models import PageRef, utcnow
from app.core.registry import WorkflowRegistry
from app.core.repo.approved_history import ApprovedHistoryRepository, HistoryQuery
from app.core.repo.decisions import DecisionRepository
from app.core.repo.edits import EditRepository
from app.core.repo.jobs import JobRepository
from app.core.status import JobStatus, SubmitOutcome, WorkItemStatus
from app.core.workflow import JobLogger
from app.workflows.lms2_approval import (
    REF_KINDS,
    ROUTE,
    WORKFLOW_LABEL,
    WORKFLOW_NAME,
    build_workflow,
    parse_link,
)
from app.workflows.lms2_approval.submission import Lms2ApprovalSubmission
from tests.support import DbTestCase
from tests.test_api import _FakeAdmin

ORG = "https://hffc.lightning.force.com"
LOAN_ID = "LAI-00533155"
URL = f"{ORG}/lightning/n/CL_Contract_Detail?c__loanId={LOAN_ID}"
KEY = "LMS2-APPROVAL-TEST"


class FakePage(Page):
    """A Page stand-in; the fake approver never touches it."""

    def __init__(self) -> None:
        """Skip Playwright's impl-bound constructor and start alive."""
        self.closed = False

    def is_closed(self) -> bool:
        """Report the test-controlled liveness flag instead of asking a browser."""
        return self.closed


class FakeTabs:
    """Tab provider that records opened URLs and hands out inert pages."""

    def __init__(self) -> None:
        """Start with nothing opened or closed."""
        self.opened: list[str] = []
        self.closed = 0

    async def new_page(self, url: str) -> Page:
        """Record the URL and return a fake page."""
        self.opened.append(url)
        return FakePage()

    async def close_page(self, page: Page) -> None:
        """Count one closed tab."""
        self.closed += 1


class FakeApprover:
    """In-memory stand-in for the LMS 2.0 approval bar interaction."""

    def __init__(self, approved: bool = True) -> None:
        """Seed the result the next call returns."""
        self.approved = approved
        self.calls = 0

    async def ensure_approved(self, page: Page, log: JobLogger) -> bool:
        """Count the call and report the seeded result."""
        self.calls += 1
        log("fake approval")
        return self.approved


def settings_for(root: Path) -> Settings:
    """Settings pointing at a temp data dir; only paths and the org matter."""
    return Settings(
        org_base=ORG,
        data_dir=root,
        db_path=root / "app.db",
        workers=3,
        refresh_interval_s=30.0,
        timeouts=TimeoutPolicy(),
        login_wait_s=1,
        headless=True,
        update_policy="auto",
    )


class ParseLinkTests(unittest.TestCase):
    """One pasted line becomes one canonical contract row."""

    def test_full_link_drops_extra_parameters(self) -> None:
        row = parse_link(URL + "&extra=ignored", ORG)
        self.assertEqual(row.key, LOAN_ID)
        self.assertEqual(row.href, URL)

    def test_bare_loan_id_is_expanded(self) -> None:
        row = parse_link(f"  {LOAN_ID}  ", ORG)
        self.assertEqual(row.key, LOAN_ID)
        self.assertEqual(row.href, URL)

    def test_my_salesforce_host_is_accepted(self) -> None:
        link = URL.replace("hffc.lightning.force.com", "hffc.my.salesforce.com")
        self.assertEqual(parse_link(link, ORG).key, LOAN_ID)

    def test_other_host_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not on the Salesforce org"):
            parse_link(URL.replace("hffc.lightning.force.com", "evil.example"), ORG)

    def test_link_without_the_loan_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "c__loanId"):
            parse_link(f"{ORG}/lightning/n/CL_Contract_Detail", ORG)

    def test_empty_line_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            parse_link("   ", ORG)

    def test_schemeless_url_is_not_mistaken_for_a_loan_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "bare loan id"):
            parse_link("hffc.lightning.force.com/lightning/n/CL_Contract_Detail", ORG)


class BuilderTests(DbTestCase):
    """The workflow declares a manual intake and no refresh cycle."""

    def test_builds_a_list_less_manual_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workflow = build_workflow(settings_for(Path(root)), self.deps())
        self.assertEqual(workflow.name, WORKFLOW_NAME)
        self.assertEqual(workflow.route, ROUTE)
        self.assertEqual(workflow.label, WORKFLOW_LABEL)
        self.assertIsNone(workflow.list_view)
        self.assertIsNone(workflow.extraction)
        self.assertIsNotNone(workflow.intake)
        self.assertEqual([ref.kind for ref in REF_KINDS], ["lms2_cl_contract"])
        self.assertEqual(workflow.terminal_labels[WorkItemStatus.COMPLETED], "Approved")


class QueueLinksTests(DbTestCase):
    """Pasted links create items, jobs and the durable history snapshot."""

    def build(
        self, *, paused: bool = False
    ) -> tuple[
        WorkItemService,
        WorkflowRegistry,
        JobRepository,
        ApprovedHistoryRepository,
    ]:
        """Wire the service around the real new workflow."""
        deps = self.deps()
        with tempfile.TemporaryDirectory() as root:
            workflow = build_workflow(settings_for(Path(root)), deps)
        registry = WorkflowRegistry()
        registry.register(workflow)
        jobs = JobRepository(self.db)
        history = ApprovedHistoryRepository(self.db)
        service = WorkItemService(
            registry,
            deps.items,
            deps.fields,
            deps.attributes,
            deps.refs,
            EditRepository(self.db),
            DecisionRepository(self.db),
            jobs,
            deps.events,
            lambda: paused,
            history,
        )
        return service, registry, jobs, history

    def test_one_link_creates_an_item_a_ref_and_a_job(self) -> None:
        service, _registry, jobs, history = self.build()
        result = service.queue_links(WORKFLOW_NAME, [URL])
        self.assertEqual((result.queued, result.skipped), (1, 0))
        self.assertEqual(result.rejected, [])

        item = self.deps().items.require(WORKFLOW_NAME, LOAN_ID)
        self.assertIs(item.status, WorkItemStatus.SUBMITTING)
        self.assertEqual(item.record_url, URL)
        ref = self.deps().refs.for_item(WORKFLOW_NAME, LOAN_ID)["lms2_cl_contract"]
        self.assertEqual(ref.url, URL)
        job = jobs.active_for(WORKFLOW_NAME, LOAN_ID)
        assert job is not None
        self.assertIs(job.status, JobStatus.QUEUED)

        page, total = history.page(WORKFLOW_NAME, HistoryQuery())
        self.assertEqual(total, 1)
        self.assertEqual(page[0].key, LOAN_ID)
        self.assertIs(page[0].status, WorkItemStatus.SUBMITTING)

    def test_repasting_a_link_is_idempotent(self) -> None:
        service, _registry, jobs, history = self.build()
        service.queue_links(WORKFLOW_NAME, [URL])
        again = service.queue_links(WORKFLOW_NAME, [URL])
        self.assertEqual((again.queued, again.skipped), (0, 1))
        item = self.deps().items.require(WORKFLOW_NAME, LOAN_ID)
        self.assertIs(item.status, WorkItemStatus.SUBMITTING)
        job = jobs.active_for(WORKFLOW_NAME, LOAN_ID)
        assert job is not None
        self.assertEqual(jobs.counts()["queued"], 1)
        self.assertEqual(history.page(WORKFLOW_NAME, HistoryQuery())[1], 1)

    def test_bad_line_is_reported_without_storing_anything(self) -> None:
        service, _registry, _jobs, _history = self.build()
        result = service.queue_links(WORKFLOW_NAME, ["https://evil.example/contract"])
        self.assertEqual((result.queued, result.skipped), (0, 0))
        self.assertEqual(len(result.rejected), 1)
        self.assertIn("not on the Salesforce org", result.rejected[0].reason)
        self.assertIsNone(self.deps().items.get(WORKFLOW_NAME, "contract"))

    def test_paused_service_refuses_the_batch(self) -> None:
        service, _registry, _jobs, _history = self.build(paused=True)
        with self.assertRaises(ApiError) as raised:
            service.queue_links(WORKFLOW_NAME, [URL])
        self.assertEqual(raised.exception.status_code, 409)

    def test_empty_batch_is_rejected(self) -> None:
        service, _registry, _jobs, _history = self.build()
        with self.assertRaises(ApiError) as raised:
            service.queue_links(WORKFLOW_NAME, ["  "])
        self.assertEqual(raised.exception.status_code, 422)

    def test_collection_post_queues_links_and_reports_bad_lines(self) -> None:
        service, registry, _jobs, _history = self.build()
        client = TestClient(create_app(registry, service, _FakeAdmin()))
        response = client.post(
            "/api/lms2-approvals",
            json={"links": [URL, "https://evil.example/contract"]},
        )
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["queued"], 1)
        self.assertEqual(body["skipped"], 0)
        self.assertEqual(len(body["rejected"]), 1)
        self.assertEqual(body["rejected"][0]["link"], "https://evil.example/contract")

        workflows = client.get("/api/workflows").json()
        approval = next(
            item for item in workflows if item["name"] == WORKFLOW_NAME
        )
        self.assertEqual(approval["label"], WORKFLOW_LABEL)
        self.assertIsNone(approval["listUrl"])
        self.assertEqual(approval["refKinds"], ["lms2_cl_contract"])

        history = client.get("/api/lms2-approvals/history")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["total"], 1)


class SubmissionTests(DbTestCase):
    """The approval pipeline's success and failure paths."""

    def build(
        self,
        *,
        status: WorkItemStatus = WorkItemStatus.SUBMITTING,
        approver: FakeApprover | None = None,
        with_ref: bool = True,
    ) -> tuple[Lms2ApprovalSubmission, FakeTabs, FakeApprover]:
        """Create one item in the requested status and wire the pipeline."""
        deps = self.deps()
        deps.items.create_present(
            WORKFLOW_NAME,
            ListRow(key=KEY, href=URL, columns={}, approved_at=None),
            utcnow(),
        )
        if with_ref:
            deps.refs.replace(
                WORKFLOW_NAME,
                KEY,
                [
                    PageRef(
                        WORKFLOW_NAME,
                        KEY,
                        "lms2_cl_contract",
                        LOAN_ID,
                        URL,
                    )
                ],
            )
        deps.items.transition(WORKFLOW_NAME, KEY, WorkItemStatus.READY)
        deps.items.transition(WORKFLOW_NAME, KEY, WorkItemStatus.SUBMITTING)
        if status is not WorkItemStatus.SUBMITTING:
            for step in (
                WorkItemStatus.APPLYING,
                WorkItemStatus.VALIDATING,
                WorkItemStatus.EXECUTING,
            ):
                deps.items.transition(WORKFLOW_NAME, KEY, step)
                if status is step:
                    break
        chosen = approver or FakeApprover()
        pipeline = Lms2ApprovalSubmission(
            WORKFLOW_NAME,
            deps.items,
            deps.refs,
            deps.events,
            chosen,
            timeouts=TimeoutPolicy(),
        )
        return pipeline, FakeTabs(), chosen

    def run_pipeline(
        self, pipeline: Lms2ApprovalSubmission, tabs: FakeTabs
    ) -> SubmitOutcome:
        """Run one approval on a fresh event loop."""
        item = self.deps().items.require(WORKFLOW_NAME, KEY)
        return asyncio.run(pipeline.run(item, tabs, lambda _line: None))

    def test_pending_contract_is_approved_and_reaches_executing(self) -> None:
        pipeline, tabs, approver = self.build()
        outcome = self.run_pipeline(pipeline, tabs)
        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        self.assertEqual(approver.calls, 1)
        self.assertEqual(tabs.opened, [URL])
        item = self.deps().items.require(WORKFLOW_NAME, KEY)
        self.assertIs(item.status, WorkItemStatus.EXECUTING)
        self.assertEqual(item.reason, "approved")

    def test_refused_contract_parks_for_review(self) -> None:
        pipeline, tabs, _approver = self.build(
            approver=FakeApprover(approved=False)
        )
        outcome = self.run_pipeline(pipeline, tabs)
        self.assertIs(outcome, SubmitOutcome.FAILED)
        item = self.deps().items.require(WORKFLOW_NAME, KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)
        self.assertIn("approved state", item.reason or "")

    def test_missing_link_fails_without_opening_a_tab(self) -> None:
        pipeline, tabs, approver = self.build(with_ref=False)
        outcome = self.run_pipeline(pipeline, tabs)
        self.assertIs(outcome, SubmitOutcome.FAILED)
        self.assertEqual(approver.calls, 0)
        self.assertEqual(tabs.opened, [])
        item = self.deps().items.require(WORKFLOW_NAME, KEY)
        self.assertIs(item.status, WorkItemStatus.NEEDS_REVIEW)

    def test_retry_resumes_from_applying(self) -> None:
        pipeline, tabs, approver = self.build(status=WorkItemStatus.APPLYING)
        outcome = self.run_pipeline(pipeline, tabs)
        self.assertIs(outcome, SubmitOutcome.COMPLETED)
        self.assertEqual(approver.calls, 1)
        item = self.deps().items.require(WORKFLOW_NAME, KEY)
        self.assertIs(item.status, WorkItemStatus.EXECUTING)


if __name__ == "__main__":
    unittest.main()
