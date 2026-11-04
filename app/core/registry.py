"""Registry of workflows available to the process.

Populated by literal imports in ``main.py`` — no dynamic discovery, no entry points.
"""

from __future__ import annotations

from app.core.errors import UnknownWorkflow

from .workflow import Workflow


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    def register(self, workflow: Workflow) -> None:
        self._workflows[workflow.name] = workflow

    def get(self, name: str) -> Workflow:
        workflow = self._workflows.get(name)
        if workflow is None:
            raise UnknownWorkflow(name)
        return workflow

    def all(self) -> tuple[Workflow, ...]:
        return tuple(self._workflows.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._workflows)
