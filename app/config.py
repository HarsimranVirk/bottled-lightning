"""Settings (org URLs, data dir, update policy, network profile; env-overridable)."""

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SF_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
SETTINGS_FILENAME = "settings.json"
ORG_BASE = os.environ.get("SF_ORG_BASE", "https://hffc.lightning.force.com")
REQUEST_TIMEOUT_MS = 60_000
LOGIN_WAIT_SECONDS = 600
HOST = os.environ.get("SF_HOST", "0.0.0.0")
PORT = int(os.environ.get("SF_PORT", "8765"))
IS_SOURCE_CHECKOUT = (BASE_DIR / "frontend" / "src").exists()
UPDATE_POLICY = os.environ.get("SF_UPDATE_POLICY", "auto")
UPDATE_AUTO_START = True
UPDATE_ALLOW_SOURCE = os.environ.get("SF_UPDATE_ALLOW_SOURCE", "0") == "1"
UPDATE_STATE_FILE = DATA_DIR / "update_state.json"
UPDATE_INSTALL_DIR = DATA_DIR / "updates"
UPDATE_CHECK_TTL_HOURS = float(os.environ.get("SF_UPDATE_CHECK_HOURS", "6"))

MAX_WORKERS = 5
DEFAULT_WORKERS = 3


class NetworkProfile(StrEnum):
    """
    How patient the browser is with this machine's connection.

    A closed set rather than a raw number, so the operator picks an outcome ("how long
    may a submit take") and nothing downstream has to validate a range.

    Example:
        profile = NetworkProfile(os.environ.get("SF_NETWORK_PROFILE", "default"))
    """

    FAST = "fast"
    """Low-latency link (office wifi): 180 s per submission."""

    DEFAULT = "default"
    """The shipped baseline: 300 s, which reproduces the original 60 s per-action wait."""

    SLOW = "slow"
    """VPN, mobile tethering or a congested link: 600 s."""


#: Whole-submission budget per profile, in seconds.
_PROFILE_BUDGET_S: Mapping[NetworkProfile, int] = {
    NetworkProfile.FAST: 180,
    NetworkProfile.DEFAULT: 300,
    NetworkProfile.SLOW: 600,
}


@dataclass(frozen=True, slots=True)
class SubmissionTimeouts:
    """
    The four budgets one run works under, all derived from a single profile.

    The ratios keep a submission bounded at every level: one action (a single
    navigation, click or wait), one object stage (its whole read or write), and the run
    as a whole. Deriving them in one place means no call site does arithmetic.

    Example (default profile):
        SubmissionTimeouts(NetworkProfile.DEFAULT, 60_000, 75_000, 150_000, 300_000)
    """

    profile: NetworkProfile
    """The profile these numbers came from; shown in the settings dialog and job log."""

    action_ms: int
    """Budget for one browser action/wait in milliseconds. Never below
    :data:`REQUEST_TIMEOUT_MS`, so a faster profile cannot make extraction or the list
    refresh *less* patient than the shipped default."""

    stage_read_ms: int
    """Budget for reading all targets of one object, in milliseconds (budget / 4)."""

    stage_write_ms: int
    """Budget for writing all targets of one object, in milliseconds (budget / 2)."""

    submission_ms: int
    """Whole-run budget for one submission or extraction, in milliseconds."""

    @classmethod
    def for_profile(cls, profile: NetworkProfile) -> SubmissionTimeouts:
        """Derive all four budgets from one profile, clamping the action floor."""
        budget_ms = _PROFILE_BUDGET_S[profile] * 1000
        return cls(
            profile=profile,
            action_ms=max(REQUEST_TIMEOUT_MS, budget_ms // 5),
            stage_read_ms=budget_ms // 4,
            stage_write_ms=budget_ms // 2,
            submission_ms=budget_ms,
        )


class TimeoutPolicy:
    """
    The live timeouts, swappable at runtime so a settings change applies to the next job.

    ``Settings`` is frozen and built once, but every consumer already holds the one
    ``Settings`` object. This holder is what they read, so changing the profile needs no
    re-wiring: the next wait sees the new values. Swapping a frozen
    :class:`SubmissionTimeouts` is a single reference assignment, so concurrent workers
    always read one consistent snapshot without a lock.

    A running job snapshots :meth:`current` when it starts (its budget and stage caps are
    pinned), but per-action waits read it live.

    Example:
        policy = TimeoutPolicy()
        policy.current().action_ms                    # 60_000
        policy.set_profile(NetworkProfile.SLOW).action_ms  # 120_000
    """

    def __init__(self, profile: NetworkProfile = NetworkProfile.DEFAULT) -> None:
        """Start on one profile (the boot default when ``settings.json`` is absent)."""
        self._current = SubmissionTimeouts.for_profile(profile)

    def current(self) -> SubmissionTimeouts:
        """The timeouts in force right now (a frozen snapshot)."""
        return self._current

    def set_profile(self, profile: NetworkProfile) -> SubmissionTimeouts:
        """Switch profiles; the next read sees it. Returns the new snapshot."""
        self._current = SubmissionTimeouts.for_profile(profile)
        return self._current


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime configuration, built once in ``main()`` and injected."""

    org_base: str
    """Salesforce Lightning base URL used for every navigation and link, e.g.
    ``https://hffc.lightning.force.com``."""

    data_dir: Path
    """Directory holding runtime state (``app.db``, browser profiles, update state); the
    OS app-data dir for installed builds, ``./data`` in a source checkout."""

    db_path: Path
    """Absolute path to ``app.db``; the only store, including the session snapshot."""

    workers: int
    """Concurrent job workers, clamped to 1..``MAX_WORKERS`` (5)."""

    refresh_interval_s: float
    """Seconds between automatic list refreshes of every workflow."""

    timeouts: TimeoutPolicy
    """Live browser timeouts and the network profile they were derived from; read through
    :meth:`TimeoutPolicy.current` so a settings change applies to the next job."""

    login_wait_s: int
    """How long the manual login waits for a human to finish, in seconds (600)."""

    headless: bool
    """Run the browser without a window; ``False`` only for manual debugging."""

    update_policy: str
    """Self-update behaviour: ``auto`` installs at boot when a newer release exists,
    ``check`` only reports, ``off`` disables the GitHub lookup."""

    host: str = "0.0.0.0"
    """Interface the HTTP server binds to; ``0.0.0.0`` exposes the LAN."""

    port: int = 8765
    """TCP port the HTTP server listens on."""

    dev_tools: bool = True
    """Whether the hidden ``/dev/db`` explorer is mounted; ``SF_DEV_TOOLS=0`` disables it."""

    dev_tools_allow_remote: bool = False
    """Whether ``/dev/db`` accepts non-loopback clients; loopback-only unless explicitly
    enabled, because the explorer reads the whole database."""


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_profile() -> NetworkProfile:
    """
    The boot-default profile from ``SF_NETWORK_PROFILE``.

    An unknown value is only a typo in an env var, so it logs and falls back to
    ``default`` instead of failing at boot.
    """
    raw = os.environ.get("SF_NETWORK_PROFILE")
    if raw is None:
        return NetworkProfile.DEFAULT
    try:
        return NetworkProfile(raw.strip().lower())
    except ValueError:
        logger.warning("unknown SF_NETWORK_PROFILE %r; using default", raw)
        return NetworkProfile.DEFAULT


def read_profile(path: Path) -> NetworkProfile | None:
    """
    The profile saved in ``settings.json``, or ``None`` when there is nothing usable.

    Absent file means "never chosen on this machine", so the caller falls back to the
    env default. A malformed file, a non-object, a missing key or an unknown value is
    logged and also returns ``None``: a bad settings file must never stop the app from
    booting.
    """
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("cannot read %s: %s; using the default profile", path, exc)
        return None
    try:
        raw = json.loads(text)
    except ValueError:
        logger.warning("%s is not valid JSON; using the default profile", path)
        return None
    if not isinstance(raw, dict):
        logger.warning("%s does not hold an object; using the default profile", path)
        return None
    value = raw.get("network_profile")
    if not isinstance(value, str):
        logger.warning("%s has no network_profile; using the default profile", path)
        return None
    try:
        return NetworkProfile(value.strip().lower())
    except ValueError:
        logger.warning("%s has unknown profile %r; using the default", path, value)
        return None


def write_profile(path: Path, profile: NetworkProfile) -> None:
    """
    Persist the chosen profile, atomically.

    Writes a sibling temp file and renames it over the target, so a crash or a
    concurrent reader never sees a half-written file. ``OSError`` propagates: the API
    call that asked for the change must report that it was not saved.
    """
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"network_profile": profile.value}))
    os.replace(temp, path)


def load_settings() -> Settings:
    workers = min(MAX_WORKERS, max(1, _env_int("SF_DEVIATION_WORKERS", DEFAULT_WORKERS)))
    return Settings(
        org_base=ORG_BASE,
        data_dir=DATA_DIR,
        db_path=DB_PATH,
        workers=workers,
        refresh_interval_s=float(_env_int("SF_RESYNC_INTERVAL_SECONDS", 30)),
        timeouts=TimeoutPolicy(read_profile(DATA_DIR / SETTINGS_FILENAME) or _env_profile()),
        login_wait_s=LOGIN_WAIT_SECONDS,
        headless=os.environ.get("SF_HEADLESS", "1") != "0",
        update_policy=UPDATE_POLICY,
        host=HOST,
        port=PORT,
        dev_tools=os.environ.get("SF_DEV_TOOLS", "1") != "0",
        dev_tools_allow_remote=os.environ.get("SF_DEV_TOOLS_ALLOW_REMOTE", "0")
        == "1",
    )
