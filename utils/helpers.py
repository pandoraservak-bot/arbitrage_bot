# Вспомогательные функции
import json
import logging
import time
import hashlib
import hmac
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

def generate_order_id(prefix: str = "ord") -> str:
    """Генерация уникального ID ордера"""
    timestamp = int(time.time() * 1000)
    random_part = int.from_bytes(hashlib.sha256(str(time.perf_counter()).encode()).digest()[:4], 'big')
    return f"{prefix}_{timestamp}_{random_part:08x}"

def calculate_signature(api_secret: str, message: str) -> str:
    """Расчет HMAC подписи для API запросов"""
    return hmac.new(
        api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def format_price(price: float, precision: int = 4) -> str:
    """Форматирование цены"""
    return f"{price:.{precision}f}"

def format_percent(value: float) -> str:
    """Форматирование процентов"""
    return f"{value:.3f}%"

def calculate_spread(bid: float, ask: float) -> float:
    """Расчет спреда в процентах"""
    if bid == 0 or ask == 0:
        return 0.0
    return ((ask - bid) / bid) * 100

def calculate_net_profit(gross_profit: float, fees: float, slippage: float = 0.0001) -> float:
    """Расчет чистой прибыли с учетом комиссий и проскальзывания"""
    return gross_profit - fees - slippage

def load_json_file(filepath: str) -> Optional[Dict]:
    """Загрузка JSON файла"""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        return None

def save_json_file(filepath: str, data: Dict) -> bool:
    """Сохранение данных в JSON файл"""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")
        return False

def timestamp_to_datetime(timestamp: float) -> str:
    """Конвертация timestamp в читаемую дату"""
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

def validate_config(config: Dict) -> bool:
    """Валидация конфигурации"""
    required_fields = [
        'MIN_SPREAD_ENTER',
        'MIN_SPREAD_EXIT',
        'MAX_POSITION_CONTRACTS',
        'MAX_DAILY_LOSS'
    ]
    
    for field in required_fields:
        if field not in config:
            logger.error(f"Missing required config field: {field}")
            return False
    
    # Проверка значений
    if config['MIN_SPREAD_ENTER'] <= config['MIN_SPREAD_EXIT']:
        logger.error("MIN_SPREAD_ENTER must be greater than MIN_SPREAD_EXIT")
        return False
    
    if config['MAX_POSITION_CONTRACTS'] <= 0:
        logger.error("MAX_POSITION_CONTRACTS must be positive")
        return False
    
    return True

def safe_float_convert(value: Any, default: float = 0.0) -> float:
    """Безопасное преобразование в float"""
    try:
        if isinstance(value, str):
            return float(value.replace(',', ''))
        return float(value)
    except (ValueError, TypeError):
        return default

def truncate_number(number: float, decimals: int = 8) -> float:
    """Обрезка числа до указанного количества знаков"""
    factor = 10 ** decimals
    return int(number * factor) / factor

class PerformanceTimer:
    """Таймер для измерения производительности"""
    
    def __init__(self, name: str = "Operation"):
        self.name = name
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        elapsed = self.end_time - self.start_time
        logger.debug(f"{self.name} completed in {elapsed:.4f}s")
    
    def get_elapsed(self) -> float:
        """Получение времени выполнения"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        elif self.start_time:
            return time.perf_counter() - self.start_time
        return 0.0