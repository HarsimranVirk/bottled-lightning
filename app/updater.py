"""GitHub-release self-update (version check + wheel verify)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from . import config

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

logger = logging.getLogger(__name__)

__all__ = [
    "UpdateError",
    "_fetch_json",
    "_validate_url",
    "apply_pending",
    "check_for_update",
    "current_version",
    "is_newer",
    "mark_installing",
    "select_wheel_asset",
    "sha256_file",
    "status",
    "verify_wheel",
]


class UpdateError(Exception):
    """Raised for an update that must not be installed (bad URL, version or digest)."""


_state: dict[str, JsonValue] = {
    "status": "idle",
    "detail": "",
    "result": None,
}
_state_lock = threading.Lock()


def current_version() -> str:
    """The running package version, without a leading v."""
    from . import __version__

    return __version__


def is_newer(candidate: str, current: str) -> bool:
    """True when ``candidate`` is a higher version than ``current``."""
    def _parse(v: str) -> tuple[int, ...] | None:
        """Split a version into comparable integer segments."""
        v = v.strip().lstrip("vV")
        m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v)
        if not m:
            return None
        nums = tuple(int(x) for x in m.group(1).split("."))
        suffix = m.group(2)
        if suffix:
            return None  # pre-release / garbage -> not considered newer
        return nums

    c = _parse(candidate)
    cur = _parse(current)
    if c is None or cur is None:
        return False
    # pad
    n = max(len(c), len(cur))
    c = c + (0,) * (n - len(c))
    cur = cur + (0,) * (n - len(cur))
    return c > cur


def select_wheel_asset(assets: Iterable[dict[str, str]]) -> dict[str, str] | None:
    """Pick the wheel to install: project wheel first, then newest version."""
    wheels = [a for a in assets if str(a.get("name", "")).endswith(".whl")]
    if not wheels:
        return None
    # prefer project wheel names
    project = [
        a
        for a in wheels
        if "bottled" in str(a.get("name", "")).lower()
        or "bottled_lightning" in str(a.get("name", "")).lower()
    ]
    pool = project if project else wheels

    # newest version by parsing name
    def _ver(a: dict[str, str]) -> tuple[int, ...]:
        m = re.search(r"-(\d+(?:\.\d+)+)", str(a.get("name", "")))
        if not m:
            return (0,)
        return tuple(int(x) for x in m.group(1).split("."))

    return max(pool, key=_ver)


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file, used to verify a downloaded wheel."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_url(url: str) -> str:
    """Refuse any download that is not served by GitHub."""
    if not url.startswith("https://github.com/"):
        raise UpdateError("url must be a github https url")
    if not url.startswith("https://"):
        raise UpdateError("url must be https")
    return url


def verify_wheel(path: Path, expected_version: str | None = None) -> None:
    """Check a wheel's embedded version and (when provided) its digest."""
    if not zipfile.is_zipfile(path):
        raise UpdateError("not a valid wheel")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "app/__init__.py" not in names:
            raise UpdateError("missing app/__init__.py")
        data = z.read("app/__init__.py").decode("utf-8", errors="replace")
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', data)
        if not m:
            raise UpdateError("version not found in wheel")
        ver = m.group(1)
        if expected_version is not None:
            ev = expected_version.lstrip("vV")
            if ver != ev:
                raise UpdateError(f"version mismatch: {ver} != {ev}")


def _fetch_json(url: str, timeout: int = 30) -> dict[str, JsonValue]:
    """GET a JSON object from the GitHub API."""
    req = urllib.request.Request(url, headers={"User-Agent": "bottled-lightning"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise UpdateError("invalid json")
        return payload


def _state_file() -> Path:
    """Path of the cached update state file."""
    return getattr(config, "UPDATE_STATE_FILE", config.DATA_DIR / "update_state.json")


def _load_cache() -> dict[str, JsonValue] | None:
    """Read the cached check result, or None when absent/unreadable."""
    try:
        data = json.loads(_state_file().read_text())
        if isinstance(data, dict):
            return data
    except OSError, ValueError, KeyError, TypeError:
        pass
    return None


def _save_cache(result: dict[str, JsonValue]) -> None:
    """Persist the last check result (best effort)."""
    try:
        _state_file().write_text(json.dumps(result))
    except OSError:
        pass


def _fresh(cached: dict[str, JsonValue]) -> bool:
    """Whether a cached result is still inside the check TTL."""
    checked = cached.get("checked_at")
    if not isinstance(checked, str):
        return False
    try:
        at = datetime.fromisoformat(checked)
    except ValueError:
        return False
    if at.tzinfo is None:
        return False
    return datetime.now(UTC) - at < timedelta(hours=config.UPDATE_CHECK_TTL_HOURS)


def _set_status(status: str, detail: str = "", **fields: JsonValue) -> None:
    """Update the in-memory status snapshot under the lock."""
    with _state_lock:
        _state["status"] = status
        _state["detail"] = detail
        for k, v in fields.items():
            if isinstance(v, (str, bool)) or v is None:
                _state[k] = v


def _publish(result: dict[str, JsonValue]) -> None:
    """Copy the operator-visible fields of a result into the in-memory status.

    Runs under ``_state_lock`` on the calling thread (FastAPI threadpool for a manual
    check, the ``sf-auto-update`` thread for the loop). Only scalars move, so a loose
    payload can never smuggle a container into ``_state``.
    """
    with _state_lock:
        for k, v in result.items():
            if isinstance(v, (str, bool)) or v is None:
                _state[k] = v


def _finish(
    result: dict[str, JsonValue], *, persist: bool = True
) -> dict[str, JsonValue]:
    """Stamp, optionally persist, publish a check result, then return it.

    ``persist=False`` is the failure path: the result is visible to ``GET /api/updates``
    immediately but never becomes a cache entry, so the next non-forced check really goes
    to the network instead of replaying the failure for the whole TTL.
    """
    stamped: dict[str, JsonValue] = {
        **result,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    if persist:
        _save_cache(stamped)
    _publish(stamped)
    return stamped


def _cached_check() -> dict[str, JsonValue] | None:
    """A fresh cached *successful* check, or ``None``.

    A ``failed`` row written by an older version is treated as a cache miss rather than
    migrated: the file is presentation state, and ignoring the row is enough to stop the
    six-hour replay. Successful rows keep their normal TTL behaviour.
    """
    cached = _load_cache()
    if cached is None or cached.get("status") == "failed":
        return None
    if not _fresh(cached):
        return None
    return cached


def _github_repo() -> str:
    """The GitHub repository releases are read from."""
    return "harsimranvirk/bottled-lightning"


def _asset_records(value: JsonValue) -> list[dict[str, str]]:
    """Coerce the release ``assets`` JSON into typed records.

    GitHub returns a list of objects; anything that is not a dict of strings is
    dropped rather than guessed at.
    """
    if not isinstance(value, list):
        return []
    records: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        record: dict[str, str] = {}
        for key, field in item.items():
            if isinstance(key, str) and isinstance(field, str):
                record[key] = field
        records.append(record)
    return records


def _reason(error: BaseException) -> str:
    """One operator-readable line for a failed check or download.

    ``urlopen`` wraps the real cause in ``urllib.error.URLError.reason``, so a certificate
    failure arrives as ``URLError(SSLCertVerificationError(…))``. The three cases that
    actually happen at boot (untrusted chain, timeout, name resolution) become a sentence
    the card can print; anything else falls back to ``str(error)`` so nothing is lost.
    """
    if isinstance(error, urllib.error.URLError):
        cause = error.reason
        if isinstance(cause, BaseException):
            return _reason(cause)
    if isinstance(error, ssl.SSLCertVerificationError):
        return (
            "couldn't verify GitHub's certificate — check the network, VPN or proxy, "
            "then try again"
        )
    if isinstance(error, ssl.SSLError):
        return (
            "the TLS connection to GitHub failed — check the network, VPN or proxy, "
            "then try again"
        )
    if isinstance(error, TimeoutError):
        return "timed out contacting GitHub — check the network and try again"
    if isinstance(error, socket.gaierror):
        return "couldn't reach api.github.com — check the network and try again"
    return str(error) or type(error).__name__


def _failed(reason: str, detail: str | None = None) -> dict[str, JsonValue]:
    """Build the canonical failed-check payload.

    ``reason`` is the operator-facing sentence, ``detail`` the raw cause for support. The
    release fields are explicitly ``None`` so a failure never renders a stale tag or URL
    next to the error.
    """
    return {
        "status": "failed",
        "update_available": False,
        "latest": None,
        "download_url": None,
        "sha256": None,
        "error": reason,
        "detail": detail if detail is not None else reason,
    }


def check_for_update(force: bool = False) -> dict[str, JsonValue]:
    """Ask GitHub for the latest release and describe what the app should do.

    Never raises: a missing repo, network failure or malformed release is a normal
    ``failed`` result that the UI reports. Results are cached in the update state
    file unless ``force`` is set.
    """
    result: dict[str, JsonValue]
    if config.UPDATE_POLICY == "off":
        result = {
            "status": "disabled",
            "update_available": False,
            "detail": "updates disabled",
        }
        _finish(result)
        return result
    if not force:
        cached = _cached_check()
        if cached is not None:
            return cached
    try:
        url = f"https://api.github.com/repos/{_github_repo()}/releases/latest"
        payload = _fetch_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result = {
                "status": "up-to-date",
                "update_available": False,
                "detail": "no releases",
                "error": None,
            }
            _finish(result)
            return result
        result = _failed(f"GitHub returned HTTP {e.code}", str(e))
        _finish(result, persist=False)
        return result
    except (OSError, ValueError) as e:
        result = _failed(_reason(e), str(e))
        _finish(result, persist=False)
        return result

    tag = str(payload.get("tag_name", ""))
    wheel = select_wheel_asset(_asset_records(payload.get("assets")))
    if wheel is None:
        result = _failed("missing wheel asset")
        _finish(result)
        return result

    download_url = wheel.get("browser_download_url", "")
    try:
        _validate_url(download_url)
    except UpdateError as e:
        result = _failed(str(e))
        _finish(result)
        return result

    available = is_newer(tag, current_version())
    digest = str(wheel.get("digest", ""))
    sha = digest.removeprefix("sha256:") if digest.startswith("sha256:") else None
    result = {
        "status": "update-available" if available else "up-to-date",
        "update_available": available,
        "latest": tag,
        "download_url": download_url,
        "sha256": sha,
        "error": None,
        "detail": "ok",
    }
    _finish(result)
    return result


def mark_installing(latest: str) -> None:
    """Publish the installing state before the background install thread starts."""
    _set_status(
        "installing",
        f"installing {latest}",
        update_available=True,
        latest=latest,
        error=None,
    )


def _download_path(url: str, latest: str) -> Path:
    """Destination for the wheel, under the data dir, named from the asset."""
    directory = config.UPDATE_INSTALL_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = Path(urlparse(url).path).name or f"bottled_lightning-{latest}.whl"
    return directory / name


def _download(url: str, path: Path) -> None:
    """Stream the wheel from its GitHub URL to ``path``."""
    request = urllib.request.Request(
        _validate_url(url), headers={"User-Agent": "bottled-lightning"}
    )
    with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as target:
        while chunk := response.read(65536):
            target.write(chunk)


def _install(path: Path) -> None:
    """Install the verified wheel into the running interpreter's environment."""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", str(path)],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"pip could not run: {exc}") from exc
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = " | ".join(output[-5:]) if output else "no output"
        raise UpdateError(f"pip install failed: {tail}")


def _restart() -> None:
    """Replace this process with the freshly installed version."""
    os.execv(sys.executable, [sys.executable, "-m", "app.main", *sys.argv[1:]])


def apply_pending(
    guard: Callable[[], str | None] | None = None,
    stop: Callable[[], None] | None = None,
) -> dict[str, JsonValue]:
    """
    Download, verify and install the pending wheel, then restart.

    Called on a background thread by ``AdminService``. ``guard`` is re-checked here so a
    job that starts between the request and the download still cancels the install;
    ``stop`` closes the browser before the process is replaced. Never raises: every
    failure is published as a ``failed`` status and leaves the current app running.
    """
    if guard is not None:
        reason = guard()
        if reason is not None:
            _set_status("blocked", reason)
            return status()

    result = check_for_update(force=True)
    if not bool(result.get("update_available")):
        return status()
    url = result.get("download_url")
    latest = result.get("latest")
    if not isinstance(url, str) or not isinstance(latest, str):
        _set_status("failed", "release has no wheel URL", error="release has no wheel URL")
        return status()

    digest = result.get("sha256")
    expected = digest.lower() if isinstance(digest, str) else None
    path = _download_path(url, latest)
    try:
        mark_installing(latest)
        _download(url, path)
        if expected is not None:
            actual = sha256_file(path)
            if actual != expected:
                raise UpdateError(f"digest mismatch: {actual} != {expected}")
        verify_wheel(path, expected_version=latest)
        _install(path)
    except Exception as exc:  # noqa: BLE001 - an update must never crash the app
        raw = f"{type(exc).__name__}: {exc}"
        _set_status("failed", raw, error=_reason(exc))
        return status()
    finally:
        path.unlink(missing_ok=True)

    _set_status("installed", f"installed {latest}", latest=latest, error=None)
    if stop is not None:
        try:
            stop()
        except Exception:
            logger.exception("closing the runtime before restart failed")
    _restart()
    return status()


def status() -> dict[str, JsonValue]:
    """Snapshot of the last update check for the API."""
    with _state_lock:
        return dict(_state)
