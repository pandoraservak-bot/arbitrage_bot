@echo off
chcp 65001 >nul
title NVDA АРБИТРАЖНЫЙ БОТ
color 0A

echo ========================================
echo    NVDA АРБИТРАЖНЫЙ БОТ
echo    Bitget vs Hyperliquid
echo ========================================
echo.

:: Проверка Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не установлен или не найден в PATH
    pause
    exit /b 1
)

:: Проверка виртуального окружения
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
    echo [ИНФО] Установка недостающих зависимостей...
    pip install websocket-client aiohttp colorama python-dotenv pandas numpy -q
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости
        pause
        exit /b 1
    )
    echo [ИНФО] Зависимости установлены
) else (
    echo [ИНФО] Все зависимости установлены
)

:: Создание необходимых папок
if not exist "data" mkdir data
if not exist "data\logs" mkdir data\logs
if not exist "core" mkdir core
if not exist "utils" mkdir utils

echo.
echo ========================================
echo    ВЫБОР РЕЖИМА ОТОБРАЖЕНИЯ
echo ========================================
echo 1. Компактный режим (рекомендуется)
echo 2. Ультракомпактный режим
echo 3. Dashboard режим
echo.
set /p choice="Выберите режим (1-3, по умолчанию 1): "

:: Обновление конфига с выбранным режимом
if "%choice%"=="2" (
    echo Установка ультракомпактного режима...
    python -c "import json; config=json.load(open('config.py' if 'config.py' in open('config.py').read() else 'config.json', 'r')); config['DISPLAY_CONFIG']['DISPLAY_MODE']='ultra_compact'; json.dump(config, open('config.py' if 'config.py' in open('config.py').read() else 'config.json', 'w'), indent=2)" 2>nul || echo Используется режим по умолчанию
) else if "%choice%"=="3" (
    echo Установка dashboard режима...
    python -c "import json; config=json.load(open('config.py' if 'config.py' in open('config.py').read() else 'config.json', 'r')); config['DISPLAY_CONFIG']['DISPLAY_MODE']='dashboard'; json.dump(config, open('config.py' if 'config.py' in open('config.py').read() else 'config.json', 'w'), indent=2)" 2>nul || echo Используется режим по умолчанию
) else (
    echo Используется компактный режим (по умолчанию)
)

echo.
echo ========================================
echo    ЗАПУСК БОТА
echo ========================================
echo Параметры:
echo   Макс. позиция: 0.02 контракта
echo   Макс. дневной убыток: $4.00
echo   Спред для входа: 0.3%%
echo   Спред для выхода: 0.1%%
echo   Проскальзывание: 0.01%%
echo.
echo Нажмите Ctrl+C для остановки бота
echo.

:: Запуск бота
python main.py

echo.
echo ========================================
echo    БОТ ОСТАНОВЛЕН
echo ========================================
pause