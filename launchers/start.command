#!/bin/bash
# bottled-lightning — double-click launcher (macOS).
#
# Creates a private virtualenv under
#   ~/Library/Application Support/bottled-lightning
# installs the newest release wheel (or a wheel placed next to this file) and
# starts the webapp in this Terminal window.
#
# Updates are handled by the app itself (it re-installs the newest GitHub
# release wheel and restarts); this script only bootstraps.
#
# Env overrides: BL_HOME, BL_WHEEL, BL_REINSTALL=1, SF_UPDATE_REPO,
#                SF_DATA_DIR, SF_HOST, SF_PORT.
set -u

APP_NAME="bottled-lightning"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_HOME="${BL_HOME:-$HOME/Library/Application Support/$APP_NAME}"
VENV="$APP_HOME/venv"
PYBIN="$VENV/bin/python"
REPO="${SF_UPDATE_REPO:-harsimranvirk/bottled-lightning}"
PORT="${SF_PORT:-8765}"

# Already running? Open the existing app instead of starting a second server that
# cannot bind the port.
if curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  echo "[bottled-lightning] already running — opening http://127.0.0.1:$PORT"
  open "http://127.0.0.1:$PORT"
  exit 0
fi

mkdir -p "$APP_HOME" || exit 1

pause_exit() {
  echo
  echo "$1"
  echo
  read -r -n 1 -s -p "Press any key to close this window..."
  echo
  exit "${2:-1}"
}

find_python() {
  local candidate
  for candidate in python3.14 /opt/homebrew/bin/python3.14 \
                   /usr/local/bin/python3.14 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)' \
         >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if [ ! -x "$PYBIN" ]; then
  BASEPY="$(find_python)" || pause_exit \
    "Python 3.14+ was not found. Install it from https://www.python.org/downloads/ and run this launcher again."
  echo "[bottled-lightning] creating virtualenv in $VENV"
  "$BASEPY" -m venv "$VENV" || pause_exit "Could not create the virtualenv in $VENV."
fi

cd "$APP_HOME" || exit 1

NEED_INSTALL=0
"$PYBIN" -c "import app" >/dev/null 2>&1 || NEED_INSTALL=1
if [ "${BL_REINSTALL:-0}" = "1" ]; then NEED_INSTALL=1; fi

if [ "$NEED_INSTALL" = "1" ]; then
  SRC="${BL_WHEEL:-}"
  if [ -z "$SRC" ]; then
    # newest wheel next to the launcher (offline install)
    SRC="$(ls -t "$HERE"/bottled_lightning-*.whl 2>/dev/null | head -n 1)"
  fi
  if [ -z "$SRC" ]; then
    echo "[bottled-lightning] looking up the newest release of $REPO..."
    SRC="$("$PYBIN" "$HERE/fetch_release.py" 2>/dev/null || true)"
  fi
  if [ -z "$SRC" ]; then
    pause_exit "No installable wheel found.

Download bottled_lightning-*.whl from the GitHub releases page
(https://github.com/$REPO/releases) and place it next to this launcher,
then double-click again."
  fi
  echo "[bottled-lightning] installing $SRC"
  "$PYBIN" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  "$PYBIN" -m pip install --upgrade "$SRC" || pause_exit "Install failed: $SRC"
fi

# Keep installed state beside the venv, not inside site-packages: recreating the
# venv must not take the database and session snapshot with it.
if [ -z "${SF_DATA_DIR:-}" ]; then
  SF_DATA_DIR="$APP_HOME/data"
  export SF_DATA_DIR
fi
mkdir -p "$SF_DATA_DIR" || pause_exit "Could not create the data directory: $SF_DATA_DIR"

# Chromium is a separate download; a no-op when the matching build is present.
"$PYBIN" -m playwright install chromium >/dev/null 2>&1 || \
  echo "[bottled-lightning] warning: could not install the Chromium build" >&2

# Open the browser once the app answers; the app keeps the foreground so Ctrl-C
# and closing the window stop it normally.
(
  for _ in $(seq 1 120); do
    if ! kill -0 "$PPID" 2>/dev/null; then
      exit 1
    fi
    if curl -fsS -m 1 -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
      open "http://127.0.0.1:$PORT"
      exit 0
    fi
    sleep 1
  done
) &

exec "$PYBIN" -m app.main "$@"
