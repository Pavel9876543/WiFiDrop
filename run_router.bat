@echo off
setlocal
cd /d "%~dp0"
set "CONNECTION_MODE=router"
set "HOTSPOT_ENABLED=false"
set "CAPTIVE_PORTAL_ENABLED=false"
call run.bat
pause
