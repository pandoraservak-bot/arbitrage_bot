# config.py
import os
from datetime import datetime

# Пути к файлам
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Настройки бирж
EXCHANGE_CONFIG = {
    "BITGET_WS_URL": "wss://ws.bitget.com/v2/ws/public",
    "BITGET_SYMBOL": "NVDAUSDT",
    "BITGET_INST_TYPE": "USDT-FUTURES",
    "HYPERLIQUID_WS_URL": "wss://api.hyperliquid.xyz/ws",
    "HYPERLIQUID_SYMBOL": "xyz:NVDA",  # Формат из WebSocket сообщения
}

WS_CONFIG = {
    "BITGET_WS_URL": "wss://ws.bitget.com/v2/ws/public",
    "BITGET_SYMBOL": "NVDAUSDT",
    "BITGET_INST_TYPE": "USDT-FUTURES",
    "HYPERLIQUID_WS_URL": "wss://api.hyperliquid.xyz/ws",
    "HYPERLIQUID_SYMBOL": "xyz:NVDA",
    
    # Настройки переподключения
    "RECONNECT_ENABLED": True,
    "MAX_RECONNECT_ATTEMPTS": 10,
    "RECONNECT_DELAY": 1,  # начальная задержка в секундах
    "HEARTBEAT_INTERVAL": 30,  # интервал heartbeat в секундах
    "CONNECTION_TIMEOUT": 10,  # таймаут подключения
}

# Управление рисками
RISK_CONFIG = {
    "MAX_POSITION_CONTRACTS": 0.02,      # Максимальный размер позиции в контрактах
    "MIN_ORDER_CONTRACTS": 0.01,         # Минимальный размер ордера в контрактах
    "MAX_DAILY_LOSS": 100.0,             # Максимальный дневной убыток $
    "MAX_SLIPPAGE": 0.0001,               # Максимальное проскальзывание (0.1%)
    "SAFETY_MULTIPLIER": 0.8,            # Коэффициент безопасности
}

# Параметры торговли
TRADING_CONFIG = {
    # Пороги спреда (в десятичных долях) - ВАЛОВЫЕ СПРЕДЫ БЕЗ КОМИССИЙ
    'MIN_SPREAD_ENTER': 0.001,           # 0.1% минимальный валовый спред для входа
    'MIN_SPREAD_EXIT': -0.0002,            # 0.1% валовый спред для выхода
    
    # Параметры исполнения
    'ORDER_TYPE': 'market',              # Рыночные ордера
    'FOK_ENABLED': True,                 # Fill-or-Kill логика
    'MARKET_SLIPPAGE': 0.0001,           # 0.01% ожидаемое проскальзывание
    
    # Комиссии (taker для рыночных ордеров) - учитываются только в PnL
    'FEES': {
        'bitget': 0.00006,                # 0.006% на Bitget
        'hyperliquid': 0.00005,           # 0.005% на Hyperliquid
    },
    
    # Лимиты
    'POSITION_CHECK_INTERVAL': 0.5,      # Проверка позиций каждые 0.5с
    'MAIN_LOOP_INTERVAL': 0.1,           # 100мс основной цикл
    'MIN_ORDER_INTERVAL': 3.0,           # Минимальный интервал между ордерами (секунды)
    
    # Настройки соединений
    'DATA_TIMEOUT': 15,                  # 15 секунд таймаут для данных
    'WS_HEALTH_CHECK_INTERVAL': 5,       # Проверка здоровья соединений каждые 5 секунд
    'RECONNECT_DELAY': 2,                # 2 секунды задержка перед переподключением
    
    # Настройки мониторинга выходных спредов (даже без позиций)
    'EXIT_SPREAD_MONITORING_ENABLED': True,  # Включить мониторинг выходных спредов без позиций
    'EXIT_SPREAD_UPDATE_INTERVAL': 0.5,      # Интервал обновления выходных спредов (секунды)
}

# Настройки диагностики
DIAGNOSTIC_CONFIG = {
    'LOG_DIAGNOSIS_INTERVAL': 30,        # Интервал диагностики в секундах
    'ENABLE_DETAILED_LOGGING': True,     # Включить детальное логирование
    'LOG_EXIT_SPREAD_CALCULATION': True, # Логировать расчет спреда выхода
    'MAX_SPREAD_HISTORY': 100,           # Максимальная история спредов в позиции
}

# Настройки логирования
LOGGING_CONFIG = {
    'LOG_FILE': os.path.join(LOG_DIR, f"arbitrage_{datetime.now().strftime('%Y%m%d')}.log"),
    'TRADES_FILE': os.path.join(LOG_DIR, "trades.csv"),
    'LOG_LEVEL': 'DEBUG',
    'LOG_FORMAT': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
}

# Статистика
STATS_CONFIG = {
    'UPDATE_INTERVAL': 0.5,                # Обновление статистики каждые 5 сек
    'SAVE_INTERVAL': 60,                 # Сохранение каждые 60 сек
}

# API Keys Configuration (loaded from environment variables or Replit secrets)
API_CONFIG = {
    # Hyperliquid - loaded from environment at runtime
    'HYPERLIQUID_SECRET_KEY': os.environ.get('HYPERLIQUID_SECRET_KEY', ''),
    'HYPERLIQUID_ACCOUNT_ADDRESS': os.environ.get('HYPERLIQUID_ACCOUNT_ADDRESS', ''),
    
    # Bitget - loaded from environment at runtime
    'BITGET_API_KEY': os.environ.get('BITGET_API_KEY', ''),
    'BITGET_SECRET_KEY': os.environ.get('BITGET_SECRET_KEY', ''),
    'BITGET_PASSPHRASE': os.environ.get('BITGET_PASSPHRASE', ''),
}

# Trading Mode
TRADING_MODE = {
    'MODE': 'paper',  # Options: 'paper', 'live'
    'LIVE_ENABLED': False,  # Safety switch for live trading
    'CONFIRM_BEFORE_TRADE': True,  # Require confirmation for live trades
}

# Настройки отображения
DISPLAY_CONFIG = {
    'DISPLAY_MODE': 'dashboard',          # Варианты: 'compact', 'ultra_compact', 'dashboard'
    'SHOW_SLIPPAGE_DETAILS': True,       # Показывать детали проскальзывания
    'SHOW_MARKET_DEPTH': True,           # Показывать глубину рынка
    'MAX_POSITIONS_SHOWN': 3,            # Максимум показываемых позиций
    'SHOW_SPREAD_STATS': True,           # Показывать статистику спредов
    'SHOW_PORTFOLIO_DETAILS': True,      # Показывать детали портфеля
    'SHOW_GROSS_SPREAD_NOTICE': True,    # Показывать заметку о валовых спредах
    'SHOW_BEST_SPREADS_SESSION': True,   # Показывать лучшие спреды за сессию
    'SHOW_MARKET_EXIT_SPREADS': True,    # Показывать рыночные выходные спреды (даже без позиций)
    'BEST_SPREADS_HISTORY_SIZE': 1000,   # Размер истории для лучших спредов
    'MARKET_EXIT_UPDATE_INTERVAL': 0.5,  # Интервал обновления рыночных выходных спредов
}