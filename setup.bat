@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo [WiFiDrop] Install Python 3.12 or newer first.
    pause
    exit /b 1
)

py -3 -c "import sys; raise SystemExit(sys.version_info ^< (3, 12))"
if errorlevel 1 (
    echo [WiFiDrop] Python 3.12 or newer is required.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 (
    echo [WiFiDrop] Could not create the virtual environment.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
type nul > ".venv\.wifidrop-ready"
echo [WiFiDrop] Installation completed. Run run.bat to start the server.
pause
exit /b 0

:error
echo [WiFiDrop] Installation failed. Check the messages above.
pause
exit /b 1
