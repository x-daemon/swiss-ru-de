@echo off
rem ======================================================================
rem  swiss-ru-de - complete installation for Windows (one click)
rem
rem   1. Python 3.12 (only if no Python 3.10+ is installed)
rem   2. swiss-ru-de with all translators (+ NVIDIA GPU support if a card is found)
rem   3. Local AI: Ollama + a translation model that fits the graphics card
rem   4. Speech models (downloaded now, so the first start is fast)
rem   5. "Swiss RU-DE" shortcuts on the desktop and in the Start menu
rem   6. Starts the app
rem
rem  Safe to run again: it updates what is already there.
rem  SWISS_SETUP_CI=1 (automated test): skips the big downloads and does not start the app.
rem ======================================================================
setlocal
cd /d "%~dp0"
title swiss-ru-de setup
echo.
echo  swiss-ru-de setup - takes 10 to 30 minutes and downloads up to about 12 GB.
echo  Keep this window open until it says "Done".
echo.

rem ---------------------------------------------------------------- 1. Python
echo [1/6] Python ...
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
    echo       Installing Python 3.12 ...
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY goto :nopython
echo       OK

rem ------------------------------------------------------ 2. App and packages
echo.
echo [2/6] swiss-ru-de and its packages ...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || goto :failed
)
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
set "EXTRAS=all"
where nvidia-smi >nul 2>nul && set "EXTRAS=all,gpu"
if "%EXTRAS%"=="all,gpu" echo       NVIDIA graphics card found: also installing the CUDA libraries (about 1 GB).
".venv\Scripts\python.exe" -m pip install -e ".[%EXTRAS%]" || goto :failed
copy /y pyproject.toml ".venv\installed-pyproject.toml" >nul
> ".venv\installed-extras.txt" echo %EXTRAS%
echo       OK

rem ------------------------------------------------------------ 3. Local AI
echo.
echo [3/6] Local AI (Ollama + translation model) ...
if defined SWISS_SETUP_CI goto :skip_downloads
call install-local-ai.bat nopause
if errorlevel 1 (
    echo       Local AI is not available - the app uses another translator; see README.
)

rem ------------------------------------------------------- 4. Speech models
echo.
echo [4/6] Speech models (about 3 GB, once) ...
".venv\Scripts\python.exe" -c "from swiss_ru_de.asr import resolve_model; from faster_whisper import download_model; resolve_model('swiss-turbo', print); download_model('large-v3-turbo'); print('      Speech models ready.')"
if errorlevel 1 echo       Not downloaded now - the app downloads them at its first start.
:skip_downloads

rem ------------------------------------------------------------ 5. Shortcuts
echo.
echo [5/6] Shortcuts ...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make-shortcuts.ps1" "%CD%"

rem ------------------------------------------------------------------ 6. Done
echo.
echo [6/6] Done! Start swiss-ru-de any time with the "Swiss RU-DE" icon on the desktop.
echo       Settings - Translator: Claude / ChatGPT / Gemini / Grok need an API key;
echo       "Local AI on this PC" and "offline" work without one.
echo.
if defined SWISS_SETUP_CI exit /b 0
start "" ".venv\Scripts\swiss-ru-de-gui.exe"
pause
exit /b 0

:nopython
echo.
echo Python could not be installed automatically. Install Python 3.12 from
echo https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.
if not defined SWISS_SETUP_CI pause
exit /b 1

:failed
echo.
echo Installation failed - see the messages above, then run install-windows.bat again.
if not defined SWISS_SETUP_CI pause
exit /b 1
