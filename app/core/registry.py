"""Registry of workflows available to the process.

Populated by literal imports in ``main.py`` — no dynamic discovery, no entry points.
"""

from __future__ import annotations

from app.core.errors import UnknownWorkflow

from .workflow import Workflow


class WorkflowRegistry:
    """The workflows this process serves, by name."""

    def __init__(self) -> None:
        """Start empty; ``main`` registers each workflow explicitly."""
        self._workflows: dict[str, Workflow] = {}

    def register(self, workflow: Workflow) -> None:
        """Add or replace a workflow by name."""
        self._workflows[workflow.name] = workflow

    def get(self, name: str) -> Workflow:
        """Return a workflow or raise ``UnknownWorkflow``."""
        workflow = self._workflows.get(name)
        if workflow is None:
            raise UnknownWorkflow(name)
        return workflow

    def all(self) -> tuple[Workflow, ...]:
        """Every registered workflow, in registration order."""
        return tuple(self._workflows.values())

    def names(self) -> tuple[str, ...]:
        """Registered names, in registration order."""
        return tuple(self._workflows)
