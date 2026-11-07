@echo off
rem Removes OLD swiss-ru-de installations: other copies of the app folder (from older
rem archives) and their Python environments, shortcuts to them, an install in the system
rem Python, speech / local AI models that are no longer used, and download caches.
rem This folder (the current installation) is kept. It asks before every deletion.
rem   cleanup-old-installs.bat          ask for each item
rem   cleanup-old-installs.bat --list   only show what would be removed
setlocal
cd /d "%~dp0"
title swiss-ru-de - remove old installations
echo.
echo  Close swiss-ru-de first (all copies), then answer the questions below:
echo  Enter = suggested answer, y = remove, n = keep.
echo.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    set "PY="
    for %%v in (3.12 3.13 3.11 3.10) do (
        if not defined PY py -%%v -c "import sys" >nul 2>nul && set "PY=py -%%v"
    )
    if not defined PY set "PY=python"
)
%PY% -m swiss_ru_de.cleanup %*
if errorlevel 1 (
    echo.
    echo The cleanup could not run. Run install-windows.bat first, then try again.
    goto :end
)
rem Shortcuts to an old copy were removed: point them to this installation again.
if exist ".venv\Scripts\swiss-ru-de-gui.exe" powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make-shortcuts.ps1" "%CD%"
:end
if not defined SWISS_SETUP_CI pause
