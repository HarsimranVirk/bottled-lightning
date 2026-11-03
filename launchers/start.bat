@echo off
rem bottled-lightning - double-click launcher (Windows).
rem
rem Creates a private virtualenv under %LOCALAPPDATA%\bottled-lightning,
rem installs the newest release wheel (or a wheel placed next to this file)
rem and starts the webapp in this window.
rem
rem Updates are handled by the app itself; this script only bootstraps.
rem
rem Env overrides: BL_HOME, BL_WHEEL, BL_REINSTALL=1, SF_UPDATE_REPO,
rem                SF_DATA_DIR, SF_HOST, SF_PORT.
setlocal EnableExtensions
title bottled-lightning

set "APP_NAME=bottled-lightning"
if not defined BL_HOME set "BL_HOME=%LOCALAPPDATA%\%APP_NAME%"
if not defined SF_UPDATE_REPO set "SF_UPDATE_REPO=harsimranvirk/bottled-lightning"
set "VENV=%BL_HOME%\venv"
set "PY=%VENV%\Scripts\python.exe"
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

if not exist "%BL_HOME%" mkdir "%BL_HOME%" 2>nul

if exist "%PY%" goto have_venv

rem --- find Python 3.14+ -----------------------------------------------------
set "BASEPY="
py -3.14 -c "import sys" >nul 2>&1 && set "BASEPY=py -3.14"
if not defined BASEPY (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,14) else 1)" >nul 2>&1 && set "BASEPY=python"
)
if not defined BASEPY goto no_python

echo [bottled-lightning] creating virtualenv in "%VENV%"
%BASEPY% -m venv "%VENV%"
if errorlevel 1 (
    echo Could not create the virtualenv in "%VENV%".
    goto fail
)

:have_venv
cd /d "%BL_HOME%"

set "NEED_INSTALL=0"
"%PY%" -c "import app" >nul 2>&1 || set "NEED_INSTALL=1"
if /i "%BL_REINSTALL%"=="1" set "NEED_INSTALL=1"
if "%NEED_INSTALL%"=="0" goto start

rem --- install: env override, wheel beside launcher, then GitHub release -----
set "SRC="
if defined BL_WHEEL set "SRC=%BL_WHEEL%"
if defined SRC goto do_install

for /f "delims=" %%F in ('dir /b /o-d "%HERE%\bottled_lightning-*.whl" 2^>nul') do (
    if not defined SRC set "SRC=%HERE%\%%F"
)
if defined SRC goto do_install

echo [bottled-lightning] looking up the newest release...
for /f "usebackq delims=" %%U in (`"%PY%" "%HERE%\fetch_release.py" 2^>nul`) do set "SRC=%%U"
if defined SRC goto do_install

echo.
echo No installable wheel found.
echo Download bottled_lightning-*.whl from the GitHub releases page
echo   https://github.com/%SF_UPDATE_REPO%/releases
echo and place it next to this launcher, then double-click again.
goto fail

:do_install
echo [bottled-lightning] installing %SRC%
"%PY%" -m pip install --quiet --upgrade pip >nul 2>&1
"%PY%" -m pip install --upgrade "%SRC%"
if errorlevel 1 (
    echo Install failed: %SRC%
    goto fail
)

:start
rem Chromium is a separate download; a no-op when the build is present.
"%PY%" -m playwright install chromium >nul 2>&1
if errorlevel 1 echo [bottled-lightning] warning: could not install the Chromium build.

"%PY%" -m app.main
if errorlevel 1 goto fail_quiet
exit /b 0

:no_python
echo.
echo Python 3.14+ was not found.
echo Install it from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH" during setup, then double-click again.
goto fail

:fail
echo.
pause
exit /b 1

:fail_quiet
echo.
echo The app exited with an error. See the messages above.
pause
exit /b 1
