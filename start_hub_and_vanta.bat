@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH.
    echo Activate your virtual environment or install Python 3.11+ and try again.
    exit /b 1
)

echo Starting hub runtime...
start "Agentic HUB Runtime" /D "%ROOT%" cmd /k "set PYTHONPATH=%PYTHONPATH% && python -m hub.main"

echo Starting control plane...
start "Agentic HUB Control Plane" /D "%ROOT%" cmd /k "set PYTHONPATH=%PYTHONPATH% && python -m control_plane.main serve"

echo Vanta is loaded by the hub from configs\agents.yaml.
echo Two windows were opened: one for the hub runtime and one for the control plane.
