"""Workflow-agnostic core: domain models, statuses, field model, workflow seam.

Modules are imported explicitly (``from app.core.models import WorkItem``); this package
deliberately re-exports nothing, to keep the core ⇄ salesforce import graph acyclic.
"""
