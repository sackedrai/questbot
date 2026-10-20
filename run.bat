@echo off
setlocal
cd /d "%~dp0"

title QuestBot

rem --- locate python ---
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [X] Python not found in PATH.
        echo     Install Python 3.10+ from python.org and try again.
        pause
        exit /b 1
    )
    set "PY=py -3"
) else (
    set "PY=python"
)

rem --- create virtual environment ---
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [X] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

set "VPY=.venv\Scripts\python.exe"

rem --- install dependencies ---
if not exist ".venv\Lib\site-packages\aiogram" (
    echo [2/3] Installing dependencies, please wait...
    "%VPY%" -m pip install --upgrade pip --quiet
    "%VPY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [X] Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    echo [2/3] Dependencies already installed.
)

rem --- run ---
echo [3/3] Starting bot...
echo.
"%VPY%" -m bot

echo.
echo Bot stopped.
pause
