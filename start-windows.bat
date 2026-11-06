@echo off
rem One-click start on Windows. First run installs everything into .venv (takes a few minutes).
rem Opens the two-pane window. Any arguments are passed to the command line tool instead,
rem e.g.:  start-windows.bat --to both --overlay
cd /d "%~dp0"

if not exist ".venv\Scripts\swiss-ru-de.exe" (
    echo Installing swiss-ru-de into .venv ...
    py -3 -m venv .venv 2>nul || python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -e ".[all]" || goto :failed
)

if "%~1"=="" (
    ".venv\Scripts\swiss-ru-de.exe" --gui
) else (
    ".venv\Scripts\swiss-ru-de.exe" %*
)
pause
exit /b

:nopython
echo Python 3.10+ is required: https://www.python.org/downloads/  (tick "Add python.exe to PATH")
pause
exit /b 1

:failed
echo Installation failed - see the messages above.
pause
exit /b 1
