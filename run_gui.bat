@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem WiFiDrop GUI launcher. Keep this file ASCII-only for cmd.exe compatibility.
net session >nul 2>&1
if errorlevel 1 (
    echo [WiFiDrop] Requesting administrator privileges...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "PYTHON_EXE="
where python.exe >nul 2>&1
if not errorlevel 1 set "PYTHON_EXE=python.exe"

if not defined PYTHON_EXE (
    where py.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=py.exe -3"
)

if not defined PYTHON_EXE (
    echo [WiFiDrop] Python 3.10 or newer was not found.
    echo [WiFiDrop] Install Python and enable the Add Python to PATH option.
    pause
    exit /b 1
)

%PYTHON_EXE% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [WiFiDrop] Python 3.10 or newer is required.
    pause
    exit /b 1
)

%PYTHON_EXE% -c "import PyQt6, fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo [WiFiDrop] Installing required Python packages...
    %PYTHON_EXE% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [WiFiDrop] Failed to install dependencies.
        pause
        exit /b 1
    )
)

echo [WiFiDrop] Starting GUI...
%PYTHON_EXE% -m app.gui
if errorlevel 1 (
    echo [WiFiDrop] GUI exited with an error.
    pause
    exit /b 1
)
exit /b 0
