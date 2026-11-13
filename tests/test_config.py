"""Network profiles: derivation, the action floor, and live application."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import (
    NetworkProfile,
    SubmissionTimeouts,
    TimeoutPolicy,
    read_profile,
    write_profile,
)
from app.salesforce.adapters import AdapterBase


class SubmissionTimeoutsTests(unittest.TestCase):
    """The four budgets derived from one profile."""

    def test_default_matches_the_shipped_action_timeout(self) -> None:
        """The default profile reproduces today's 60 s per-action wait exactly."""
        timeouts = SubmissionTimeouts.for_profile(NetworkProfile.DEFAULT)

        self.assertEqual(timeouts.action_ms, 60_000)
        self.assertEqual(timeouts.stage_read_ms, 75_000)
        self.assertEqual(timeouts.stage_write_ms, 150_000)
        self.assertEqual(timeouts.submission_ms, 300_000)

    def test_fast_cannot_tighten_extraction_or_refresh(self) -> None:
        """A fast profile shortens the run, never the per-action wait below 60 s."""
        timeouts = SubmissionTimeouts.for_profile(NetworkProfile.FAST)

        self.assertEqual(timeouts.action_ms, 60_000)
        self.assertEqual(timeouts.submission_ms, 180_000)

    def test_slow_relaxes_every_level(self) -> None:
        """A slow profile doubles the default at each level."""
        timeouts = SubmissionTimeouts.for_profile(NetworkProfile.SLOW)

        self.assertEqual(timeouts.action_ms, 120_000)
        self.assertEqual(timeouts.stage_read_ms, 150_000)
        self.assertEqual(timeouts.stage_write_ms, 300_000)
        self.assertEqual(timeouts.submission_ms, 600_000)


class TimeoutPolicyTests(unittest.TestCase):
    """The mutable holder every consumer reads instead of a boot-time int."""

    def test_set_profile_applies_to_the_next_read(self) -> None:
        """Switching profiles is visible without rebuilding the settings object."""
        policy = TimeoutPolicy()
        self.assertIs(policy.current().profile, NetworkProfile.DEFAULT)

        policy.set_profile(NetworkProfile.SLOW)

        self.assertIs(policy.current().profile, NetworkProfile.SLOW)
        self.assertEqual(policy.current().action_ms, 120_000)

    def test_adapter_reads_the_policy_live(self) -> None:
        """An adapter already constructed picks up a new profile on its next wait."""
        policy = TimeoutPolicy()
        adapter = AdapterBase("https://org", policy)
        self.assertEqual(adapter._timeout_ms, 60_000)

        policy.set_profile(NetworkProfile.SLOW)

        self.assertEqual(adapter._timeout_ms, 120_000)

class SettingsFileTests(unittest.TestCase):
    """The per-machine profile file: round-trip, absent and malformed files."""

    def setUp(self) -> None:
        """Give each test an empty directory for its settings file."""
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"

    def tearDown(self) -> None:
        """Remove the temporary directory."""
        self._tmp.cleanup()

    def test_round_trip(self) -> None:
        """A written profile is read back, and the file is plain JSON."""
        write_profile(self.path, NetworkProfile.SLOW)

        self.assertIs(read_profile(self.path), NetworkProfile.SLOW)
        self.assertEqual(
            self.path.read_text(), '{"network_profile": "slow"}'
        )

    def test_absent_file_is_none(self) -> None:
        """No file means "never chosen here", so the env default applies."""
        self.assertIsNone(read_profile(self.path))

    def test_malformed_files_fall_back(self) -> None:
        """Bad JSON, a non-object and an unknown value all return None."""
        for text in ('{"network_profile": ', "[]", '{"network_profile": "turbo"}', "{}"):
            with self.subTest(text=text):
                self.path.write_text(text)
                self.assertIsNone(read_profile(self.path))
