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

python.exe -c "import qrcode, PIL, zeroconf, idna" >nul 2>&1
if errorlevel 1 del ".venv\.wifidrop-ready" >nul 2>&1
if not exist ".venv\.wifidrop-ready" (
    echo [WiFiDrop] Installing dependencies. Internet is only needed for this first setup...
    "python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :install_error
    "python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :install_error
    if not exist ".venv" mkdir ".venv"
    type nul > ".venv\.wifidrop-ready"
)

echo.
set CONNECTION_MODE=router
set HOTSPOT_ENABLED=false
set CAPTIVE_PORTAL_ENABLED=false
echo [WiFiDrop] Starting through router...
echo.
"python.exe" start.py
exit /b %errorlevel%

:install_error
echo.
echo [WiFiDrop] Dependency installation failed. Check your internet connection and try again.
pause
exit /b 1
