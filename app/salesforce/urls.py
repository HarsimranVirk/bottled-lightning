"""Salesforce URL builders shared by every workflow.

Keeping the URL shapes here means a workflow package never has to know how the org
base, object API name and list filter combine, and ``Settings`` stays free of
per-workflow Salesforce internals.
"""

from __future__ import annotations


def list_view_url(org_base: str, object_api: str, filter_name: str) -> str:
    """
    Build a Lightning list-view URL for one object and filter.

    Called once per workflow at boot, from that workflow's ``build_workflow``, to
    populate its ``ListViewSpec``. ``org_base`` is the Lightning host root (for this
    org ``https://hffc.lightning.force.com``), ``object_api`` is the object API name
    (``Consumer_Loan_Deviation__c``) and ``filter_name`` is the list-view filterName
    parameter (``Z2_Loan_para_pricing1``).

    The result is the URL the browser runtime opens; it is not the printable-view
    popup URL used during extraction.

    Example:
        list_view_url("https://hffc.lightning.force.com",
                      "Consumer_Loan_Deviation__c", "Z2_Loan_para_pricing1")
    """
    return f"{org_base}/lightning/o/{object_api}/list?filterName={filter_name}"
