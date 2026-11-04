"""Error taxonomy shared by every workflow.

The worker translates these into job outcomes (see docs/class-design-deviations.md §8.3);
pipelines raise them and never decide retries themselves.
"""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class for all domain failures."""


class UnknownWorkflow(WorkflowError):
    """A workflow name was not registered."""


class UnknownAdapter(WorkflowError):
    """A workflow has no adapter for an object kind."""


class InvalidTransition(WorkflowError):
    """A status change is not allowed by the state machine."""


class LeaseHeld(WorkflowError):
    """A terminal status was attempted while a job lease was still active."""


class SessionExpired(WorkflowError):
    """Salesforce showed the login page; a manual login is required."""


class TransientBrowserError(WorkflowError):
    """Navigation/rendering failure that is worth one retry."""


class AmbiguousRecord(WorkflowError):
    """Salesforce matched more than one candidate record; never guess."""


class MissingRecord(WorkflowError):
    """A required record or page could not be found."""


class SaveRejected(WorkflowError):
    """Salesforce rejected a write (validation rule, read-only field, …)."""


class ValueMismatch(WorkflowError):
    """A written value did not read back as written."""


class AlreadyClosed(WorkflowError):
    """The item is already gone from Salesforce; not an error."""
