"""Shared unittest support: one migrated temp database per test."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
