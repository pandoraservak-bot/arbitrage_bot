@echo off
chcp 65001 >nul
title NVDA Арбитражный Бот
color 0A
echo ========================================
echo    NVDA Арбитражный Бот
echo    Bitget vs Hyperliquid
echo ========================================
echo.

:: Проверка Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не установлен или не добавлен в PATH
    pause
    exit /b 1
)

:: Активация виртуального окружения
if exist "venv\Scripts\activate.bat" (
    echo [ИНФО] Активация виртуального окружения...
    call venv\Scripts\activate.bat
) else (
    echo [ИНФО] Виртуальное окружение не найдено
)

:: Проверка зависимостей
echo.
echo [ИНФО] Проверка зависимостей...
python -c "import websocket, aiohttp, colorama" 2>nul
if errorlevel 1 (
    echo [ИНФО] Установка отсутствующих зависимостей...
    pip install websocket-client aiohttp colorama python-dotenv pandas numpy -q
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости
        pause
        exit /b 1
    )
    echo [ОК] Зависимости установлены
) else (
    echo [ОК] Все зависимости установлены
)

:: Создание директорий
if not exist "data" mkdir data
if not exist "data\logs" mkdir data\logs
if not exist "core" mkdir core
if not exist "utils" mkdir utils

echo.
echo ========================================
echo    Режим отображения: Dashboard
echo ========================================
echo.
echo Параметры торговли:
echo   Макс. размер позиции: 0.02 контракта
echo   Макс. размер позиции USD: $4.00
echo   Порог входа: 0.3%%
echo   Порог выхода: 0.1%%
echo   Проскальзывание: 0.01%%
echo.
echo Нажмите Ctrl+C для остановки бота
echo.

:: Запуск бота
python main.py
echo.
echo ========================================
echo    Бот остановлен
echo ========================================
pause
