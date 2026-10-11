@echo off
chcp 65001 >nul
setlocal EnableExtensions
pushd "%~dp0"
if errorlevel 1 (
    echo [WiFiDrop] Не удалось открыть папку проекта.
    pause
    exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
    echo [WiFiDrop] Git не найден. Установите Git for Windows и включите его в PATH.
    pause
    exit /b 1
)
if not exist ".git" (
    echo [WiFiDrop] Эта папка не является клоном репозитория.
    echo Скачайте проект командой git clone https://github.com/Pavel9876543/WiFiDrop.git
    pause
    exit /b 1
)

echo [WiFiDrop] Обновление проекта. Перед обновлением закройте WiFiDrop.
rem Блок считывается до git pull: обновление самого update.bat не прерывает выполнение.
(
    git pull --ff-only
    if errorlevel 1 (
        echo.
        echo [WiFiDrop] Обновление не выполнено. Причина указана Git выше.
        echo Проверьте интернет, локальные изменения и настройку удалённой ветки.
        pause
        exit /b 1
    )
    echo.
    echo [WiFiDrop] Обновление завершено. Запустите WiFiDrop заново.
    pause
    exit /b 0
)
