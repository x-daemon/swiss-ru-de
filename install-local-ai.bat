@echo off
rem Installs Ollama (local AI on this PC) and a translation model, then switches
rem swiss-ru-de to "Local AI". Run it once; it can be run again safely.
setlocal EnableDelayedExpansion
cd /d "%~dp0"
rem "nopause" = called from install-windows.bat
set "NOPAUSE=%~1"

set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if exist "%OLLAMA%" goto :have_ollama
for /f "delims=" %%p in ('where ollama 2^>nul') do (
    set "OLLAMA=%%p"
    goto :have_ollama
)

echo.
echo === 1/4  Installing Ollama ...
winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
if not exist "%OLLAMA%" (
    echo winget did not work - downloading the official installer from ollama.com ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing https://ollama.com/download/OllamaSetup.exe -OutFile \"$env:TEMP\OllamaSetup.exe\""
    if not exist "%TEMP%\OllamaSetup.exe" goto :failed
    echo Please click through the Ollama installer that opens now ...
    "%TEMP%\OllamaSetup.exe"
)
if not exist "%OLLAMA%" goto :failed

:have_ollama
echo.
echo === 2/4  Ollama: "%OLLAMA%"
"%OLLAMA%" list >nul 2>nul
if errorlevel 1 (
    echo Starting the Ollama server ...
    start "Ollama" /min "%OLLAMA%" serve
    timeout /t 5 /nobreak >nul
)

rem Choose the model by graphics memory. It must fit NEXT TO the two speech models
rem (about 2.5 GB) and Windows, or Ollama runs part of it on the processor - minutes behind.
rem TranslateGemma (Google's translation model) translates much better than a general
rem model of the same size: 4b (about 3 GB) for 8-12 GB cards, 12b from 16 GB.
set "MODEL=translategemma:4b"
set "FALLBACK=gemma3:4b"
for /f "tokens=1" %%m in ('nvidia-smi --query-gpu=memory.total --format=csv^,noheader^,nounits 2^>nul') do (
    if %%m GEQ 15000 set "MODEL=translategemma:12b"
    if %%m GEQ 15000 set "FALLBACK=gemma3:12b"
)
echo.
echo === 3/4  Downloading the model !MODEL! (once; 3-8 GB) ...
"%OLLAMA%" pull !MODEL!
if errorlevel 1 (
    echo !MODEL! is not available - using !FALLBACK! instead.
    set "MODEL=!FALLBACK!"
    "%OLLAMA%" pull !FALLBACK!
)
if errorlevel 1 goto :failed

echo.
echo === 4/4  Switching swiss-ru-de to Local AI ...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "from swiss_ru_de.settings import load_settings, save_settings; s = load_settings(); s.translator = 'local'; s.local_model = '!MODEL!'; s.local_url = 'http://localhost:11434/v1'; save_settings(s); print('Settings saved: Translator = Local AI, model = !MODEL!')"
) else (
    echo swiss-ru-de is not installed yet: run start-windows.bat, then choose
    echo Settings - Translator - Local AI on this PC - model !MODEL!.
)

echo.
echo Done. Local AI is ready. Start swiss-ru-de with start-windows.bat
echo (if it is already open: close and start it again).
if /i not "%NOPAUSE%"=="nopause" pause
exit /b 0

:failed
echo.
echo Something went wrong - see the messages above. Manual way:
echo   1. install Ollama from https://ollama.com/download
echo   2. in a terminal:  ollama pull translategemma:4b
echo   3. swiss-ru-de Settings - Translator - Local AI on this PC
if /i not "%NOPAUSE%"=="nopause" pause
exit /b 1
