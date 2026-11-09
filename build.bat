@echo off
rem Build dist\FilmContactSheets\FilmContactSheets.exe
rem   build.bat               full build: venv, dependencies, tests, PyInstaller
rem   build.bat --skip-tests  skip the test run
rem   build.bat --no-pause    don't wait for a key at the end (for scripts / CI)
setlocal EnableExtensions
cd /d "%~dp0"

set "SKIP_TESTS="
set "NO_PAUSE="
:args
if "%~1"=="" goto :start
if /i "%~1"=="--skip-tests" set "SKIP_TESTS=1"
if /i "%~1"=="--no-pause" set "NO_PAUSE=1"
shift
goto :args
:start

call :find_python || goto :error
set "VPY=%~dp0.venv\Scripts\python.exe"

echo.
echo [1/4] Virtual environment
if not exist "%VPY%" %PY% -m venv .venv || goto :error

echo.
echo [2/4] Installing dependencies. The first run downloads about 100 MB, mostly Qt.
"%VPY%" -m pip install --disable-pip-version-check --upgrade pip || goto :error
"%VPY%" -m pip install --disable-pip-version-check -r requirements-dev.txt || goto :error

echo.
if defined SKIP_TESTS goto :skip_tests
echo [3/4] Running tests. Any single test stuck for 2 minutes is failed, not waited on.
set "QT_QPA_PLATFORM=offscreen"
"%VPY%" -m pytest -q --timeout=120 || goto :error
set "QT_QPA_PLATFORM="
goto :pyinstaller
:skip_tests
echo [3/4] Tests skipped

:pyinstaller
echo.
echo [4/4] PyInstaller. This takes several minutes and can sit quietly on
echo       "Looking for dynamic libraries" or "Building COLLECT"; antivirus scanning
echo       makes it slower. That is normal.
"%VPY%" -m PyInstaller --noconfirm contact_sheet.spec || goto :error

echo.
echo Built dist\FilmContactSheets\FilmContactSheets.exe
if not defined NO_PAUSE pause
exit /b 0

:find_python
rem Prefer the py launcher: a bare "python" may be the Microsoft Store stub,
rem which opens the Store instead of running anything.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python 3.11 or newer was not found. Install it from python.org and tick "Add python.exe to PATH".
    exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if errorlevel 1 (
    echo %PY% is missing, too old, or the Microsoft Store placeholder. Python 3.11 or newer is required.
    exit /b 1
)
exit /b 0

:error
echo.
echo Build failed. See the messages above.
if not defined NO_PAUSE pause
exit /b 1
