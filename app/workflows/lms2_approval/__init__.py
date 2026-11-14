"""The LMS2 Contract Approval workflow: manual links, automatic approval.

The operator pastes LMS 2.0 CL contract links (or bare loan IDs) into the app; each
accepted line becomes one item and one ``SUBMIT`` job. There is no list view, no
extraction and no review decision: the job opens the contract and approves it using the
same page interaction as the deviation workflow's pre-write gate.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from functools import partial
from urllib.parse import parse_qs, quote, urlsplit

from app.config import Settings
from app.core.list_view import ListRow
from app.core.status import WorkItemStatus
from app.core.workflow import LinkIntake, RefKind, Workflow, WorkflowDeps
from app.salesforce.adapters import AdapterRegistry
from app.workflows.deviations_z02.adapters.lms2 import Lms2ClContractAdapter

from .submission import CONTRACT_KIND, Lms2ApprovalSubmission

WORKFLOW_NAME = "lms2_approval"
WORKFLOW_LABEL = "LMS2 Contract Approval"
ROUTE = "lms2-approvals"

#: Lightning custom detail page that hosts the LMS 2.0 contract approval bar.
DETAIL_PATH = "CL_Contract_Detail"
#: Query parameter carrying the LMS 2.0 loan id on that page.
LOAN_ID_PARAM = "c__loanId"
#: A bare identifier, never a URL missing its scheme (which would otherwise be treated
#: as a loan id and produce an unopenable link).
_BARE_LOAN_ID = re.compile(r"[A-Za-z0-9_-]+")


class ApprovalObject(StrEnum):
    """SF object kinds this workflow links to."""

    LMS2_CL_CONTRACT = CONTRACT_KIND


#: The single stored link per item; readiness and submission both read this declaration.
REF_KINDS: tuple[RefKind, ...] = (RefKind(ApprovalObject.LMS2_CL_CONTRACT.value),)


def _detail_url(org_base: str, loan_id: str) -> str:
    """Build the canonical LMS 2.0 contract detail URL for one loan id."""
    return (
        f"{org_base}/lightning/n/{DETAIL_PATH}"
        f"?{LOAN_ID_PARAM}={quote(loan_id, safe='')}"
    )


def _allowed_hosts(org_base: str) -> frozenset[str]:
    """
    Hosts a pasted link may use: the Lightning host and its Salesforce counterpart.

    Operators copy links from either the Lightning domain or the ``my.salesforce.com``
    domain; both open the same org. Any other host is rejected so a malformed paste can
    never make the browser open an arbitrary site.
    """
    host = urlsplit(org_base).hostname
    if host is None:
        return frozenset()
    hosts = {host.lower()}
    if host.endswith(".lightning.force.com"):
        hosts.add(host.replace(".lightning.force.com", ".my.salesforce.com").lower())
    return frozenset(hosts)


def parse_link(text: str, org_base: str) -> ListRow:
    """
    Turn one pasted line into an item row, or raise ``ValueError`` with a reason.

    Accepts a full same-org LMS 2.0 contract link (with ``c__loanId``) or a bare loan
    id. The stored ``href`` is always rebuilt as the canonical detail URL, so a pasted
    link with extra query parameters or a different page still opens the approval page.
    The item key is the loan id, which makes re-pasting the same contract idempotent.

    Example:
        row = parse_link("LAI-00533155", "https://hffc.lightning.force.com")
        row.key   # "LAI-00533155"
    """
    value = text.strip()
    if not value:
        raise ValueError("empty link")
    if "://" not in value:
        if not _BARE_LOAN_ID.fullmatch(value):
            raise ValueError(
                "a bare loan id may contain only letters, digits, '-' and '_'"
            )
        return ListRow(
            key=value,
            href=_detail_url(org_base, value),
            columns={},
            approved_at=None,
        )

    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("the link must use http or https")
    host = (parts.hostname or "").lower()
    if host not in _allowed_hosts(org_base):
        raise ValueError("the link is not on the Salesforce org")
    loan_ids = parse_qs(parts.query).get(LOAN_ID_PARAM)
    loan_id = loan_ids[0].strip() if loan_ids else ""
    if not loan_id:
        raise ValueError(f"the link has no {LOAN_ID_PARAM} value")
    return ListRow(
        key=loan_id,
        href=_detail_url(org_base, loan_id),
        columns={},
        approved_at=None,
    )


def map_row(row: ListRow) -> Mapping[str, str]:
    """List columns → stored attributes; manual links carry no extra columns."""
    return {}


def build_workflow(settings: Settings, deps: WorkflowDeps) -> Workflow:
    """
    Build the manual-link approval workflow and its approval pipeline.

    Called once at boot through ``main.BUILDERS``. Construction does no browser work;
    the adapter instance is only used for its page interaction when a job runs. The
    workflow has no list view or extraction, so the stack creates no watcher for it.
    """
    approver = Lms2ClContractAdapter(settings.org_base, settings.timeouts)
    submission = Lms2ApprovalSubmission(
        WORKFLOW_NAME,
        deps.items,
        deps.refs,
        deps.events,
        approver,
        timeouts=settings.timeouts,
    )
    return Workflow(
        name=WORKFLOW_NAME,
        route=ROUTE,
        label=WORKFLOW_LABEL,
        list_view=None,
        catalog=(),
        adapters=AdapterRegistry([]),
        extraction=None,
        submission=submission,
        map_row=map_row,
        terminal_labels={WorkItemStatus.COMPLETED: "Approved"},
        ref_kinds=REF_KINDS,
        intake=LinkIntake(
            ApprovalObject.LMS2_CL_CONTRACT.value,
            partial(parse_link, org_base=settings.org_base),
        ),
    )
