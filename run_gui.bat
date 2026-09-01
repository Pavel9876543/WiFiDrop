@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if /I "%~1"=="--elevated" goto :main

rem Run the real launcher through elevated cmd.exe. The VBS wrapper only hides
rem the console and requests UAC; it does not use PowerShell.
wscript.exe //nologo "%~dp0WiFiDrop.vbs" elevate "%~f0"
exit /b 0

:main
set "PYTHON_EXE="

rem Prefer the Python launcher because it reliably selects a real Python 3
rem installation even when the Microsoft Store python.exe alias is enabled.
for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
    )
)

if not defined PYTHON_EXE (
    call :show_error "Python 3.10 or newer was not found. Install Python and enable Add Python to PATH."
    exit /b 1
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    call :show_error "WiFiDrop requires Python 3.10 or newer."
    exit /b 1
)

"%PYTHON_EXE%" -c "import PyQt6, aiofiles, fastapi, jinja2, pydantic, pydantic_settings, multipart, uvicorn" >nul 2>&1
if errorlevel 1 (
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 (
        call :show_error "Failed to install WiFiDrop dependencies. Check the Internet connection and Python installation."
        exit /b 1
    )
)

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

for %%D in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpD"
set "PYTHONW=%PYTHON_DIR%pythonw.exe"
if exist "%PYTHONW%" (
    start "" "%PYTHONW%" -X utf8 -m app.gui
) else (
    rem Fallback for unusual Python installations without pythonw.exe.
    start "" /b "%PYTHON_EXE%" -X utf8 -m app.gui
)
exit /b 0

:show_error
wscript.exe //nologo "%~dp0WiFiDrop.vbs" error %1
exit /b 0
