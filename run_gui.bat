@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_EXE="
for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)
if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
    )
)
if not defined PYTHON_EXE (
    wscript.exe //nologo "%~dp0WiFiDrop.vbs" error "Python 3.10 or newer was not found. Install Python and enable Add Python to PATH."
    exit /b 1
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    wscript.exe //nologo "%~dp0WiFiDrop.vbs" error "WiFiDrop requires Python 3.10 or newer."
    exit /b 1
)

"%PYTHON_EXE%" -c "import PyQt6, aiofiles, fastapi, jinja2, psutil, pydantic, pydantic_settings, multipart, uvicorn" >nul 2>&1
if errorlevel 1 (
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 (
        wscript.exe //nologo "%~dp0WiFiDrop.vbs" error "Failed to install WiFiDrop dependencies. Check the Internet connection and Python installation."
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
    start "" /b "%PYTHON_EXE%" -X utf8 -m app.gui
)
exit /b 0
