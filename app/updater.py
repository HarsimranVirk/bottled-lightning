"""GitHub-release self-update (version check + wheel verify)."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import urllib.request
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from . import config

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

__all__ = [
    "UpdateError",
    "_fetch_json",
    "_validate_url",
    "apply_pending",
    "apply_pending_async",
    "check_for_update",
    "current_version",
    "is_newer",
    "select_wheel_asset",
    "sha256_file",
    "start_auto_update",
    "status",
    "verify_wheel",
]


class UpdateError(Exception):
    pass


_state: dict[str, JsonValue] = {
    "status": "idle",
    "detail": "",
    "result": None,
}
_state_lock = threading.Lock()


def current_version() -> str:
    from . import __version__

    return __version__


def is_newer(candidate: str, current: str) -> bool:
    def _parse(v: str) -> tuple[int, ...] | None:
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
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_url(url: str) -> str:
    if not url.startswith("https://github.com/"):
        raise UpdateError("url must be a github https url")
    if not url.startswith("https://"):
        raise UpdateError("url must be https")
    return url


def verify_wheel(path: Path, expected_version: str | None = None) -> None:
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
    req = urllib.request.Request(url, headers={"User-Agent": "bottled-lightning"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise UpdateError("invalid json")
        return payload


def _state_file() -> Path:
    return getattr(config, "UPDATE_STATE_FILE", config.DATA_DIR / "update_state.json")


def _load_cache() -> dict[str, JsonValue] | None:
    try:
        data = json.loads(_state_file().read_text())
        if isinstance(data, dict):
            return data
    except OSError, ValueError, KeyError, TypeError:
        pass
    return None


def _save_cache(result: dict[str, JsonValue]) -> None:
    try:
        _state_file().write_text(json.dumps(result))
    except OSError:
        pass


def _fresh(cached: dict[str, JsonValue]) -> bool:
    return True


def _set_status(status: str, detail: str = "", **fields: JsonValue) -> None:
    with _state_lock:
        _state["status"] = status
        _state["detail"] = detail
        for k, v in fields.items():
            if isinstance(v, (str, bool)) or v is None:
                _state[k] = v


def _finish(result: dict[str, JsonValue]) -> dict[str, JsonValue]:
    _save_cache(result)
    with _state_lock:
        for k, v in result.items():
            if isinstance(v, (str, bool)) or v is None:
                _state[k] = v
    return result


def _github_repo() -> str:
    return "harsimranvirk/bottled-lightning"


def check_for_update(force: bool = False) -> dict[str, JsonValue]:
    if config.UPDATE_POLICY == "off":
        result = cast(
            dict[str, JsonValue],
            {"status": "disabled", "update_available": False, "detail": "updates disabled"},
        )
        _finish(result)
        return result
    if not force:
        cached = _load_cache()
        if cached is not None and _fresh(cached):
            return cached
    try:
        url = f"https://api.github.com/repos/{_github_repo()}/releases/latest"
        payload = _fetch_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result = cast(
                dict[str, JsonValue],
                {
                    "status": "up-to-date",
                    "update_available": False,
                    "detail": "no releases",
                    "error": None,
                },
            )
            _finish(result)
            return result
        result = cast(
            dict[str, JsonValue],
            {"status": "failed", "update_available": False, "error": str(e), "detail": str(e)},
        )
        _finish(result)
        return result
    except (OSError, ValueError) as e:
        result = cast(
            dict[str, JsonValue],
            {"status": "failed", "update_available": False, "error": str(e), "detail": str(e)},
        )
        _finish(result)
        return result

    tag = str(payload.get("tag_name", ""))
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        assets = []
    wheel = select_wheel_asset(cast(list[dict[str, str]], assets)) if assets else None
    if wheel is None:
        result = cast(
            dict[str, JsonValue],
            {
                "status": "failed",
                "update_available": False,
                "error": "missing wheel asset",
                "detail": "missing wheel asset",
            },
        )
        _finish(result)
        return result

    download_url = str(wheel.get("browser_download_url", ""))
    try:
        _validate_url(download_url)
    except UpdateError as e:
        result = cast(
            dict[str, JsonValue],
            {"status": "failed", "update_available": False, "error": str(e), "detail": str(e)},
        )
        _finish(result)
        return result

    available = is_newer(tag, current_version())
    result = cast(
        dict[str, JsonValue],
        {
            "status": "update-available" if available else "up-to-date",
            "update_available": available,
            "latest": tag,
            "download_url": download_url,
            "error": None,
            "detail": "ok",
        },
    )
    _finish(result)
    return result


def _apply_from(info: dict[str, str]) -> None:
    pass


def apply_pending(force_check: bool = True) -> dict[str, str]:
    if force_check:
        check_for_update(force=True)
    return {"status": "none"}


def apply_pending_async(force_check: bool = True) -> dict[str, str]:
    return apply_pending(force_check=force_check)


def status() -> dict[str, JsonValue]:
    with _state_lock:
        return dict(_state)


def start_auto_update() -> None:
    if config.UPDATE_AUTO_START:
        threading.Thread(target=lambda: check_for_update(force=False), daemon=True).start()
