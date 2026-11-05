"""The update guard: which conditions must stop an install."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from app.api.services import update_block_reason


class UpdateGuardTests(unittest.TestCase):
    """The guard is pure so the safety rules are testable without a stack."""

    def reason(
        self,
        *,
        login_running: bool = False,
        job_counts: Mapping[str, int] | None = None,
        source_checkout: bool = False,
        allow_source: bool = False,
    ) -> str | None:
        """Call the guard with safe defaults plus overrides."""
        return update_block_reason(
            login_running=login_running,
            job_counts=job_counts or {},
            source_checkout=source_checkout,
            allow_source=allow_source,
        )

    def test_idle_install_is_allowed(self) -> None:
        """No login, no jobs, installed build: safe."""
        self.assertIsNone(self.reason())

    def test_login_blocks(self) -> None:
        """A manual login must not be replaced mid-flight."""
        self.assertIn("login", str(self.reason(login_running=True)))

    def test_active_jobs_block(self) -> None:
        """Any queued, running or blocked job blocks the restart."""
        for status in ("queued", "running", "blocked_auth"):
            self.assertEqual(
                self.reason(job_counts={status: 1}), "jobs are running"
            )

    def test_source_checkout_blocks_unless_allowed(self) -> None:
        """A dev checkout is protected unless the override is explicit."""
        self.assertIn("source checkout", str(self.reason(source_checkout=True)))
        self.assertIsNone(self.reason(source_checkout=True, allow_source=True))


if __name__ == "__main__":
    unittest.main()
