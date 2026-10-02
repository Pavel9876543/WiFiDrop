@echo off
setlocal
cd /d "%~dp0"

:: Relaunch this script elevated. DHCP/DNS and network adapter configuration need Administrator.
net session >nul 2>&1
if not %errorlevel%==0 (
    echo [WiFiDrop] Administrator privileges are required. Requesting elevation...
    wscript.exe //nologo "%~dp0WiFiDrop.vbs" elevate "%~f0"
    exit /b
)

where python.exe >nul 2>nul
if errorlevel 1 (
    echo [WiFiDrop] Python not found.
    echo Install Python 3.10 or newer and add it to PATH.
    pause
    exit /b 1
)

python.exe -c "import uvicorn, qrcode, PIL, zeroconf, idna" >nul 2>nul
if errorlevel 1 (
    echo [WiFiDrop] Installing dependencies...
    python.exe -m pip install --upgrade pip
    if errorlevel 1 goto :install_error
    python.exe -m pip install -r requirements.txt
    if errorlevel 1 goto :install_error
    if not exist ".venv" mkdir ".venv"
    type nul > ".venv\.wifidrop-ready"
)

set CONNECTION_MODE=hotspot
set HOTSPOT_ENABLED=true
set CAPTIVE_PORTAL_ENABLED=true
set CAPTIVE_PORTAL_PORT=80
set CAPTIVE_PORTAL_PUBLIC_URL=

echo.
echo [WiFiDrop] Starting captive Wi-Fi hotspot...
echo.
python.exe start.py
set EXIT_CODE=%errorlevel%
echo.
pause
exit /b %EXIT_CODE%

:install_error
echo.
echo [WiFiDrop] Dependency installation failed.
pause
exit /b 1
