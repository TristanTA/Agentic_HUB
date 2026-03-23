@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH.
    exit /b 1
)

echo Starting Vanta Core guardian...
start "Vanta Core" /D "%ROOT%" cmd /k "set PYTHONPATH=%PYTHONPATH% && python -m vanta_core.main run"

echo Vanta Core will supervise Agent OS and restart it when needed.
