@echo off
rem Build dist\FilmContactSheets\FilmContactSheets.exe
setlocal
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install -r requirements-dev.txt || goto :error
python -m pytest -q || goto :error
pyinstaller --noconfirm contact_sheet.spec || goto :error
echo.
echo Built dist\FilmContactSheets\FilmContactSheets.exe
goto :eof

:error
echo Build failed.
exit /b 1
