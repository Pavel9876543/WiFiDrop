@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo [WiFiDrop] Python Launcher not found.
    echo Install Python 3.12 or newer from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [WiFiDrop] Creating a virtual environment...
    py -3 -c "import sys; raise SystemExit(sys.version_info ^< (3, 12))"
    if errorlevel 1 (
        echo [WiFiDrop] Python 3.12 or newer is required.
        pause
        exit /b 1
    )
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [WiFiDrop] Python 3.12 or newer is required.
        pause
        exit /b 1
    )
)

if not exist ".venv\.wifidrop-ready" (
    echo [WiFiDrop] Installing dependencies. Internet is only needed for this first setup...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :install_error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :install_error
    type nul > ".venv\.wifidrop-ready"
)

echo.
echo [WiFiDrop] Starting the server...
echo.
".venv\Scripts\python.exe" start.py
exit /b %errorlevel%

:install_error
echo.
echo [WiFiDrop] Dependency installation failed. Check your internet connection and try again.
pause
exit /b 1
