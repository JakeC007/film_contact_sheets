@echo off
rem Start Film Contact Sheets from source.
rem   run.bat                      open the app
rem   run.bat "D:\Scans\Roll 12"   open the app on a folder (or drag a folder onto run.bat)
rem   run.bat --console [folder]   keep a console window open to see errors
setlocal EnableExtensions
cd /d "%~dp0"

set "CONSOLE="
if /i "%~1"=="--console" (
    set "CONSOLE=1"
    shift
)
set "VPY=%~dp0.venv\Scripts\python.exe"
set "VPYW=%~dp0.venv\Scripts\pythonw.exe"

if exist "%VPY%" goto :deps
echo First run: creating a virtual environment. This downloads about 100 MB and takes a few minutes.
call :find_python || goto :error
%PY% -m venv .venv || goto :error

:deps
rem Also reinstall if Pillow is older than 13, the release with the 2026 security fixes.
"%VPY%" -c "import PySide6, numpy, tifffile, piexif, PIL; assert int(PIL.__version__.split('.')[0]) >= 13" >nul 2>nul && goto :launch
echo Installing dependencies...
"%VPY%" -m pip install --disable-pip-version-check --upgrade pip || goto :error
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt || goto :error

:launch
if defined CONSOLE goto :console
start "" "%VPYW%" -m contact_sheet %1
exit /b 0

:console
"%VPY%" -m contact_sheet %1
if errorlevel 1 pause
exit /b %errorlevel%

:find_python
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
echo Could not start. See the messages above.
pause
exit /b 1
