@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%src"
set "CONTROL_PLANE_PORT=8011"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH.
    echo Activate your virtual environment or install Python 3.11+ and try again.
    exit /b 1
)

echo Starting hub runtime...
start "Agentic HUB Runtime" /D "%ROOT%" cmd /k "set PYTHONPATH=%PYTHONPATH% && python -m hub.main"

netstat -ano | findstr /R /C:":%CONTROL_PLANE_PORT% .*LISTENING" >nul
if errorlevel 1 (
    echo Starting control plane...
    start "Agentic HUB Control Plane" /D "%ROOT%" cmd /k "set PYTHONPATH=%PYTHONPATH% && python -m control_plane.main serve"
) else (
    echo Control plane already appears to be running on port %CONTROL_PLANE_PORT%. Skipping second launch.
)

echo Vanta is loaded by the hub from configs\agents.yaml.
echo The hub runtime was launched. The control plane was launched only if port %CONTROL_PLANE_PORT% was free.
