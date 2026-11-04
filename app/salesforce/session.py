"""Session state: snapshot injection, expiry detection, refresh after manual login."""

from __future__ import annotations

import json
from pathlib import Path

from playwright._impl._api_structures import SetCookieParam
from playwright.async_api import BrowserContext, Page

from app.config import Settings
from app.core.errors import SessionExpired
from app.core.models import SessionSnapshot, to_iso, utcnow
from app.core.repo.sessions import SessionRepository

__all__ = [
    "SessionProvider",
    "cookie_params_from_state",
    "is_lightning_url",
    "is_login_url",
]


def is_login_url(url: str) -> bool:
    """Heuristic: does this URL mean not authenticated?"""
    lowered = url.lower()
    if "login" in lowered or "idp" in lowered:
        return True
    # Salesforce bounces an unauthenticated Lightning request to the classic host.
    return "ec=302" in lowered or "starturl=" in lowered


def is_lightning_url(url: str) -> bool:
    """True for an authenticated Lightning page."""
    return "/lightning/" in url and not is_login_url(url)


async def is_login_page(page: Page) -> bool:
    """
    Reliable login detection: URL heuristics plus the password input.

    Example:
        await is_login_page(page)   # True on hffc.my.salesforce.com/?ec=302…
    """
    if is_login_url(page.url):
        return True
    try:
        return await page.locator("input[type=password]").count() > 0
    except Exception:  # noqa: BLE001 - detached page counts as "cannot verify"
        return False


def cookie_params_from_state(storage_state: str) -> list[SetCookieParam]:
    """
    Convert a storage-state JSON string into ``add_cookies`` arguments.

    Each cookie is rebuilt field by field with explicit types, so nothing from
    ``json.loads`` leaks as ``Any`` into the browser API. Malformed entries are
    skipped rather than raising: a partially broken snapshot should still get the
    cookies it can.

    Example input:
        {"cookies": [{"name": "sid", "value": "abc",
                       "domain": ".lightning.force.com", "path": "/",
                       "expires": 1800000000.0, "httpOnly": true,
                       "secure": true, "sameSite": "None"}]}

    Example output:
        [{"name": "sid", "value": "abc", "domain": ".lightning.force.com",
          "path": "/", "expires": 1800000000.0, "httpOnly": True,
          "secure": True, "sameSite": "None"}]
    """
    try:
        raw: object = json.loads(storage_state)
    except ValueError:
        return []
    if not isinstance(raw, dict):
        return []
    cookies = raw.get("cookies")
    if not isinstance(cookies, list):
        return []

    params: list[SetCookieParam] = []
    for item in cookies:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        domain = item.get("domain")
        path = item.get("path")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if not isinstance(domain, str) or not isinstance(path, str):
            continue
        expires = item.get("expires")
        http_only = item.get("httpOnly")
        secure = item.get("secure")
        same_site = item.get("sameSite")
        params.append(
            SetCookieParam(
                name=name,
                value=value,
                domain=domain,
                path=path,
                expires=float(expires) if isinstance(expires, int | float) else -1.0,
                httpOnly=http_only if isinstance(http_only, bool) else False,
                secure=secure if isinstance(secure, bool) else False,
                sameSite=(
                    same_site if same_site in {"Strict", "Lax", "None"} else "Lax"
                ),
            )
        )
    return params


class SessionProvider:
    """Owns the auth snapshot and the "are we still logged in?" decision (FR-1.4)."""

    def __init__(self, repo: SessionRepository, settings: Settings) -> None:
        """Bind the snapshot repository and settings."""
        self._repo = repo
        self._settings = settings
        self._expired = False

    @property
    def expired(self) -> bool:
        """Whether the last interaction found an expired session."""
        return self._expired

    @property
    def snapshot(self) -> SessionSnapshot | None:
        """The stored snapshot, if any."""
        return self._repo.snapshot()

    def mark_expired(self) -> None:
        """Record expiry once and emit an event."""
        if not self._expired:
            self._expired = True
            self._repo.event("expired", "Salesforce returned the login page")

    def mark_restored(self) -> None:
        """Clear the expired flag after a successful login."""
        self._expired = False

    async def inject(self, context: BrowserContext) -> int:
        """Apply the stored snapshot to a fresh context. Returns the cookie count."""
        snapshot = self._repo.snapshot()
        if snapshot is None:
            return 0
        params = cookie_params_from_state(snapshot.storage_state)
        if params:
            await context.add_cookies(params)
        return len(params)

    async def reload(self, context: BrowserContext) -> int:
        """Re-apply the snapshot after a manual login, without restarting the browser."""
        self.mark_restored()
        return await self.inject(context)

    async def save(self, context: BrowserContext) -> int:
        """
        Persist the context's storage state.

        Returns the cookie count. Cookie-less snapshots are still stored so the UI can
        show that a login produced nothing — but the next job will fail fast.
        """
        state = await context.storage_state()
        cookies = state.get("cookies", [])
        count = len(cookies) if isinstance(cookies, list) else 0
        self._repo.save(json.dumps(state), count, self._settings.org_base)
        self._repo.event("snapshot", f"{count} cookies")
        self.mark_restored()
        return count

    async def ensure(self, page: Page) -> None:
        """
        Verify the page is authenticated, navigating once if needed.

        Detection is deliberately two-sided: URL heuristics catch the classic-host
        redirect (``my.salesforce.com/?ec=302``), and the DOM check catches a login form
        served at a Lightning-looking URL.

        Raises ``SessionExpired`` so the worker parks the job as ``blocked_auth``
        instead of failing it.
        """
        if is_lightning_url(page.url) and not await is_login_page(page):
            return
        target = f"{self._settings.org_base}/lightning/"
        try:
            await page.goto(
                target,
                wait_until="domcontentloaded",
                timeout=self._settings.request_timeout_ms,
            )
        except Exception as exc:  # navigation failure is an auth signal
            self.mark_expired()
            raise SessionExpired(f"cannot reach {target}: {exc}") from exc
        if is_lightning_url(page.url) and not await is_login_page(page):
            return
        self.mark_expired()
        raise SessionExpired(f"not logged in (landed on {page.url})")


def profile_dir_for(settings: Settings, name: str) -> Path:
    """Per-purpose browser profile directory."""
    return settings.data_dir / f"sf_profile_{name}"


def snapshot_age_seconds(snapshot: SessionSnapshot) -> float:
    """Age of a snapshot in seconds."""
    return (utcnow() - snapshot.created_at).total_seconds()


def describe_snapshot(snapshot: SessionSnapshot) -> str:
    """Human-readable snapshot summary for logs and the API."""
    return f"{snapshot.cookie_count} cookies @ {to_iso(snapshot.created_at)}"
