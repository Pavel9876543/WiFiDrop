@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo [WiFiDrop] Created .env from .env.example.
)

if not exist "Files" mkdir "Files"
if not exist "logs" mkdir "logs"

set "WIFIDROP_UID=1000"
set "WIFIDROP_GID=1000"
set "COMPOSE="

where docker >nul 2>nul
if errorlevel 1 goto :try_podman

docker info >nul 2>nul
if not errorlevel 1 goto :docker_ready

if not exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" goto :try_podman
echo [WiFiDrop] Starting Docker Desktop...
start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a WAIT_COUNT=0

:wait_docker
timeout /t 2 /nobreak >nul
docker info >nul 2>nul
if not errorlevel 1 goto :docker_ready
set /a WAIT_COUNT+=1
if %WAIT_COUNT% LSS 60 goto :wait_docker
goto :try_podman

:docker_ready
docker compose version >nul 2>nul
if not errorlevel 1 set "COMPOSE=docker compose"
if defined COMPOSE goto :compose_ready
where docker-compose >nul 2>nul
if not errorlevel 1 set "COMPOSE=docker-compose"
if defined COMPOSE goto :compose_ready

:try_podman
where podman >nul 2>nul
if errorlevel 1 goto :engine_error
podman info >nul 2>nul
if errorlevel 1 goto :engine_error
podman compose version >nul 2>nul
if not errorlevel 1 set "COMPOSE=podman compose"
if defined COMPOSE goto :compose_ready
where podman-compose >nul 2>nul
if not errorlevel 1 set "COMPOSE=podman-compose"
if not defined COMPOSE goto :engine_error

:compose_ready
set "PORT=8000"
for /f "usebackq tokens=1,* delims==" %%A in (".env") do if /i "%%A"=="PORT" set "PORT=%%B"

if "%~1"=="" goto :up
if /i "%~1"=="up" goto :up
if /i "%~1"=="--detach" goto :detach
if /i "%~1"=="-d" goto :detach
if /i "%~1"=="down" goto :down
if /i "%~1"=="logs" goto :logs
if /i "%~1"=="restart" goto :restart
if /i "%~1"=="status" goto :status
if /i "%~1"=="ps" goto :status
echo Usage: docker-run.bat [up^|--detach^|-d^|down^|logs^|restart^|status]
exit /b 2

:up
echo [WiFiDrop] Starting at http://localhost:%PORT% ...
%COMPOSE% up --build
exit /b %errorlevel%

:detach
%COMPOSE% up --build --detach
if errorlevel 1 exit /b %errorlevel%
echo [WiFiDrop] Running at http://localhost:%PORT%
echo [WiFiDrop] Use docker-run.bat logs or docker-run.bat down.
exit /b 0

:down
%COMPOSE% down
exit /b %errorlevel%

:logs
%COMPOSE% logs --follow
exit /b %errorlevel%

:restart
%COMPOSE% down
if errorlevel 1 exit /b %errorlevel%
goto :up

:status
%COMPOSE% ps
exit /b %errorlevel%

:engine_error
echo [WiFiDrop] Docker Compose is unavailable or the container engine is not running.
echo Install/start Docker Desktop or Podman, then try again.
pause
exit /b 1
