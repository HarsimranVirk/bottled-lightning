#!/usr/bin/env python3
"""Print the newest bottled-lightning wheel URL from GitHub releases.

Initial-install helper for the double-click launchers: at that point the app
itself is not importable, so this stays stdlib-only. Prints nothing (exit 1)
when the repo or a release is unavailable, letting the launcher fall back to a
wheel sitting next to it.
"""
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_REPO = "harsimranvirk/bottled-lightning"
WHEEL_PREFIX = "bottled_lightning-"


def main() -> int:
    repo = os.environ.get("SF_UPDATE_REPO", DEFAULT_REPO)
    url = "https://api.github.com/repos/{}/releases/latest".format(repo)
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "bottled-lightning-launcher",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    token = os.environ.get("SF_GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        print("no release for {} (HTTP {})".format(repo, exc.code), file=sys.stderr)
        return 1
    except Exception as exc:  # offline, DNS, TLS
        print("release lookup failed: {}".format(exc), file=sys.stderr)
        return 1

    assets = payload.get("assets") or []
    wheels = [a for a in assets if str(a.get("name", "")).endswith(".whl")]
    own = [a for a in wheels if str(a.get("name", "")).startswith(WHEEL_PREFIX)]
    picked = (own or wheels)[0] if (own or wheels) else None
    if not picked:
        print("release {} has no .whl asset".format(payload.get("tag_name")),
              file=sys.stderr)
        return 1
    print(picked["browser_download_url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
