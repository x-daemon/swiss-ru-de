@echo off
rem Removes what install-windows.bat set up. Your settings and API keys can stay or go.
setlocal
cd /d "%~dp0"
title swiss-ru-de uninstall
echo This removes the swiss-ru-de shortcuts, its Python environment (.venv) and,
echo if you want, the downloaded models and your settings.
choice /m "Continue"
if errorlevel 2 exit /b 0

powershell -NoProfile -Command "foreach ($f in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { Remove-Item -ErrorAction SilentlyContinue (Join-Path $f 'Swiss RU-DE.lnk') }"
if exist ".venv" rmdir /s /q ".venv"
echo Removed shortcuts and .venv.

choice /m "Also delete the downloaded speech models (about 3 GB)"
if not errorlevel 2 (
    for /d %%d in ("%USERPROFILE%\.cache\huggingface\hub\models--*whisper*") do rmdir /s /q "%%d"
    echo Speech models deleted.
)
where ollama >nul 2>nul && (
    choice /m "Also delete the local AI models from Ollama (gemma3)"
    if not errorlevel 2 (
        ollama rm gemma3:12b >nul 2>nul
        ollama rm gemma3:4b >nul 2>nul
        echo Local AI models deleted. Ollama itself: Windows Settings - Apps - Ollama - Uninstall.
    )
)
choice /m "Also delete your swiss-ru-de settings"
if not errorlevel 2 (
    if exist "%APPDATA%\swiss-ru-de" rmdir /s /q "%APPDATA%\swiss-ru-de"
    echo Settings deleted. API keys: Windows Credential Manager - entries "swiss-ru-de".
)
echo.
echo Done. You can now delete this folder.
pause
