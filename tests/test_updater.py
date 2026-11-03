"""Updater unit tests — no network, no real installs."""

import email.message
import tempfile
import unittest
import urllib.error
import zipfile
from collections.abc import Iterable
from pathlib import Path
from unittest import mock

from app import config, updater
from app.types import JsonValue


def _wheel(name: str, version: str) -> Path:
    path = Path(tempfile.mkdtemp()) / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("app/__init__.py", f'__version__ = "{version}"\n')
    return path


class VersionTests(unittest.TestCase):
    def test_newer(self) -> None:
        self.assertTrue(updater.is_newer("v0.3.1", "0.3.0"))
        self.assertTrue(updater.is_newer("0.4", "0.3.9"))
        self.assertTrue(updater.is_newer("1.0.0", "0.99.99"))

    def test_not_newer(self) -> None:
        self.assertFalse(updater.is_newer("v0.3.0", "0.3.0"))
        self.assertFalse(updater.is_newer("0.3.0rc1", "0.3.0"))
        self.assertFalse(updater.is_newer("0.2.9", "0.3.0"))

    def test_garbage_version_does_not_raise(self) -> None:
        self.assertFalse(updater.is_newer("nightly", "0.3.0"))


class AssetTests(unittest.TestCase):
    def test_prefers_project_wheel_and_newest_version(self) -> None:
        assets: list[dict[str, str]] = [
            {"name": "bottled_lightning-0.2.0-py3-none-any.whl"},
            {"name": "bottled_lightning-0.10.0-py3-none-any.whl"},
            {"name": "unrelated-9.9.9-py3-none-any.whl"},
            {"name": "notes.txt"},
        ]
        picked = updater.select_wheel_asset(assets)
        assert picked is not None
        self.assertEqual(picked["name"], "bottled_lightning-0.10.0-py3-none-any.whl")

    def test_falls_back_to_any_wheel(self) -> None:
        picked = updater.select_wheel_asset([{"name": "thing-1.0-py3-none-any.whl"}])
        assert picked is not None
        self.assertEqual(picked["name"], "thing-1.0-py3-none-any.whl")

    def test_no_wheel(self) -> None:
        self.assertIsNone(updater.select_wheel_asset([{"name": "notes.txt"}]))


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_file = Path(tmp.name) / "update_state.json"
        for patch in (
            mock.patch.object(config, "UPDATE_STATE_FILE", self.state_file),
            mock.patch.object(config, "UPDATE_POLICY", "auto"),
            mock.patch.object(updater, "current_version", return_value="0.3.0"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    @staticmethod
    def _payload(tag: str, wheels: Iterable[str] = ("0.3.0",)) -> dict[str, JsonValue]:
        return {
            "tag_name": tag,
            "published_at": "2026-01-01T00:00:00Z",
            "body": "release notes",
            "assets": [
                {
                    "name": f"bottled_lightning-{version}-py3-none-any.whl",
                    "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/"
                    f"bottled_lightning-{version}-py3-none-any.whl",
                    "digest": "sha256:deadbeef",
                }
                for version in wheels
            ],
        }

    def test_update_available(self) -> None:
        with mock.patch.object(
            updater, "_fetch_json", return_value=self._payload("v0.4.0", ["0.4.0"])
        ):
            result = updater.check_for_update(force=True)
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest"], "v0.4.0")
        self.assertIn("bottled_lightning-0.4.0", str(result.get("download_url")))
        self.assertEqual(result["status"], "update-available")
        self.assertTrue(self.state_file.exists())

    def test_up_to_date(self) -> None:
        with mock.patch.object(updater, "_fetch_json", return_value=self._payload("v0.3.0")):
            result = updater.check_for_update(force=True)
        self.assertFalse(result["update_available"])
        self.assertEqual(result["status"], "up-to-date")

    def test_missing_repo_is_not_an_error(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.github.com/x", 404, "Not Found", email.message.Message(), None
        )
        self.addCleanup(error.close)
        with mock.patch.object(updater, "_fetch_json", side_effect=error):
            result = updater.check_for_update(force=True)
        self.assertEqual(result["status"], "up-to-date")
        self.assertFalse(result["update_available"])
        self.assertIsNone(result["error"])
        self.assertIn("no releases", str(result.get("detail")))

    def test_network_failure_is_reported_not_raised(self) -> None:
        with mock.patch.object(updater, "_fetch_json", side_effect=OSError("offline")):
            result = updater.check_for_update(force=True)
        self.assertEqual(result["status"], "failed")
        self.assertIn("offline", str(result.get("error")))
        self.assertFalse(result["update_available"])

    def test_release_without_wheel_fails_loudly(self) -> None:
        payload = self._payload("v0.4.0")
        payload["assets"] = []
        with mock.patch.object(updater, "_fetch_json", return_value=payload):
            result = updater.check_for_update(force=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "missing wheel asset")

    def test_cache_avoids_repeated_github_calls(self) -> None:
        fetch = mock.Mock(return_value=self._payload("v0.4.0", ["0.4.0"]))
        with mock.patch.object(updater, "_fetch_json", fetch):
            updater.check_for_update(force=True)
            second = updater.check_for_update(force=False)
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(second["update_available"])

    def test_disabled_policy_skips_network(self) -> None:
        fetch = mock.Mock()
        with (
            mock.patch.object(config, "UPDATE_POLICY", "off"),
            mock.patch.object(updater, "_fetch_json", fetch),
        ):
            result = updater.check_for_update(force=True)
        self.assertEqual(result["status"], "disabled")
        fetch.assert_not_called()


class WheelTests(unittest.TestCase):
    def test_verify_matching_version(self) -> None:
        path = _wheel("bottled_lightning-1.2.3-py3-none-any.whl", "1.2.3")
        updater.verify_wheel(path, expected_version="v1.2.3")

    def test_verify_mismatched_version(self) -> None:
        path = _wheel("bottled_lightning-1.2.3-py3-none-any.whl", "1.2.3")
        with self.assertRaises(updater.UpdateError):
            updater.verify_wheel(path, expected_version="1.2.4")

    def test_reject_non_wheel(self) -> None:
        path = Path(tempfile.mkdtemp()) / "fake.whl"
        path.write_bytes(b"not a zip")
        with self.assertRaises(updater.UpdateError):
            updater.verify_wheel(path)

    def test_sha256(self) -> None:
        path = Path(tempfile.mkdtemp()) / "blob"
        path.write_bytes(b"abc")
        self.assertEqual(
            updater.sha256_file(path),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_download_url_must_be_github(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater._validate_url("https://evil.example.com/x.whl")
        with self.assertRaises(updater.UpdateError):
            updater._validate_url("http://github.com/x.whl")
        self.assertEqual(
            updater._validate_url("https://github.com/x.whl"), "https://github.com/x.whl"
        )


if __name__ == "__main__":
    unittest.main()
