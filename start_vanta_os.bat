@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"

set "PYTHON_BIN="
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_BIN=py -3"
)
if not defined PYTHON_BIN (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_BIN=python"
    )
)
if not defined PYTHON_BIN (
    echo Python was not found on PATH.
    exit /b 1
)

echo Starting Vanta Core guardian...
start "Vanta Core" /D "%ROOT%" cmd /k "set PYTHONPATH=%PYTHONPATH% && %PYTHON_BIN% -m vanta_core.main run"

echo Vanta Core will supervise Agent OS and restart it when needed.
