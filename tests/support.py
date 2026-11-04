"""Shared unittest support: one migrated temp database per test."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.repo.attributes import AttributeRepository
from app.core.repo.events import EventRepository
from app.core.repo.fields import FieldValueRepository
from app.core.repo.refs import PageRefRepository
from app.core.repo.work_items import WorkItemRepository
from app.core.workflow import WorkflowDeps
from app.db.connection import Database


class DbTestCase(unittest.TestCase):
    tmp_path: Path
    db: Database

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.db = Database(self.tmp_path / "test.db")
        self.db.migrate()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def deps(self) -> WorkflowDeps:
        return WorkflowDeps(
            items=WorkItemRepository(self.db),
            fields=FieldValueRepository(self.db),
            attributes=AttributeRepository(self.db),
            refs=PageRefRepository(self.db),
            events=EventRepository(self.db),
        )
