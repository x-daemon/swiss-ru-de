@echo off
rem One-click start on Windows. The first run installs everything into .venv (a few minutes);
rem later runs install updates automatically after "git pull" or a new download.
rem Opens the two-part window. Any arguments are passed to the command line tool instead,
rem e.g.:  start-windows.bat --to both --overlay
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv ...
    py -3 -m venv .venv 2>nul || python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)

set EXTRAS=all
where nvidia-smi >nul 2>nul && set EXTRAS=all,gpu

rem (Re)install when pyproject.toml changed or a GPU was added since the last install.
fc /b pyproject.toml ".venv\installed-pyproject.toml" >nul 2>nul || goto :install
findstr /x /c:"%EXTRAS%" ".venv\installed-extras.txt" >nul 2>nul || goto :install
goto :run

:install
echo Installing swiss-ru-de [%EXTRAS%] ...
if "%EXTRAS%"=="all,gpu" echo NVIDIA graphics card found: also installing the CUDA libraries (about 1 GB).
".venv\Scripts\python.exe" -m pip install -e ".[%EXTRAS%]" || goto :failed
copy /y pyproject.toml ".venv\installed-pyproject.toml" >nul
> ".venv\installed-extras.txt" echo %EXTRAS%

:run
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
