"""Session plumbing: snapshot decoding and login-page detection."""

from __future__ import annotations

import json
import unittest

from app.config import Settings
from app.core.models import utcnow
from app.core.repo.sessions import SessionRepository
from app.salesforce.runtime import BrowserRuntime
from app.salesforce.session import (
    SessionProvider,
    cookie_params_from_state,
    is_lightning_url,
    is_login_url,
)
from tests.support import DbTestCase

COOKIE = {
    "name": "sid",
    "value": "abc",
    "domain": ".lightning.force.com",
    "path": "/",
    "expires": 1800000000.5,
    "httpOnly": True,
    "secure": True,
    "sameSite": "None",
}


class UrlTests(unittest.TestCase):
    def test_login_redirect_is_detected(self) -> None:
        self.assertTrue(
            is_login_url(
                "https://hffc.my.salesforce.com/?ec=302&startURL=%2Fvisualforce%2Fsession"
            )
        )
        self.assertTrue(is_login_url("https://hffc.my.salesforce.com/login?x=1"))
        self.assertFalse(is_login_url("https://hffc.lightning.force.com/lightning/o/"))

    def test_printable_view_host_is_not_a_login_page(self) -> None:
        self.assertFalse(is_login_url("https://hffc.my.salesforce.com/a2f/x?fcf=1"))

    def test_lightning_page(self) -> None:
        self.assertTrue(
            is_lightning_url("https://hffc.lightning.force.com/lightning/o/X/list")
        )
        self.assertFalse(is_lightning_url("https://hffc.lightning.force.com/login"))
        self.assertFalse(is_lightning_url("about:blank"))


class CookieDecodingTests(unittest.TestCase):
    def test_cookie_is_rebuilt_field_by_field(self) -> None:
        params = cookie_params_from_state(json.dumps({"cookies": [COOKIE]}))
        self.assertEqual(len(params), 1)
        cookie = params[0]
        self.assertEqual(cookie["name"], "sid")
        self.assertEqual(cookie["value"], "abc")
        self.assertEqual(cookie["domain"], ".lightning.force.com")
        self.assertEqual(cookie["path"], "/")
        self.assertEqual(cookie["expires"], 1800000000.5)
        self.assertTrue(cookie["httpOnly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["sameSite"], "None")

    def test_incomplete_cookies_are_skipped(self) -> None:
        broken = {"cookies": [{"name": "no-domain"}]}
        self.assertEqual(cookie_params_from_state(json.dumps(broken)), [])

    def test_invalid_input(self) -> None:
        self.assertEqual(cookie_params_from_state("not json"), [])
        self.assertEqual(cookie_params_from_state("[]"), [])
        self.assertEqual(cookie_params_from_state('{"cookies": "nope"}'), [])


class SessionProviderTests(DbTestCase):
    def _settings(self) -> Settings:
        return Settings(
            org_base="https://example",
            data_dir=self.tmp_path,
            db_path=self.tmp_path / "app.db",
            workers=3,
            refresh_interval_s=30.0,
            request_timeout_ms=60_000,
            login_wait_s=600,
            headless=True,
            update_policy="auto",
            deviations_z02_list_url="https://example/list",
            deviations_z02_pattern=r"Deviation-\d+-\d+",
        )

    def test_expiry_flag_round_trip(self) -> None:
        provider = SessionProvider(SessionRepository(self.db), self._settings())
        self.assertFalse(provider.expired)
        provider.mark_expired()
        self.assertTrue(provider.expired)
        provider.mark_restored()
        self.assertFalse(provider.expired)

    def test_snapshot_is_exposed(self) -> None:
        repo = SessionRepository(self.db)
        repo.save(json.dumps({"cookies": [COOKIE]}), 1, "org")
        provider = SessionProvider(repo, self._settings())
        snapshot = provider.snapshot
        assert snapshot is not None
        self.assertEqual(snapshot.cookie_count, 1)
        self.assertLess(snapshot.created_at, utcnow())


class RuntimeGuardTests(DbTestCase):
    def test_run_before_start_raises(self) -> None:
        settings = Settings(
            org_base="https://example",
            data_dir=self.tmp_path,
            db_path=self.tmp_path / "app.db",
            workers=1,
            refresh_interval_s=30.0,
            request_timeout_ms=1000,
            login_wait_s=1,
            headless=True,
            update_policy="auto",
            deviations_z02_list_url="https://example/list",
            deviations_z02_pattern=r"Deviation-\d+-\d+",
        )
        runtime = BrowserRuntime(settings, SessionProvider(SessionRepository(self.db), settings))
        self.assertFalse(runtime.started)

        async def work() -> None:
            return None

        with self.assertRaises(RuntimeError):
            runtime.run(work)
        with self.assertRaises(RuntimeError):
            runtime.new_tab_group()


if __name__ == "__main__":
    unittest.main()
