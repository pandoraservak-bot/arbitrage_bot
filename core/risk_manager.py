# Менеджер управления рисками
import time
import logging
from typing import Dict, Tuple
from datetime import datetime, timedelta
import json
import os

from config import RISK_CONFIG, DATA_DIR

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self):
        self.config = RISK_CONFIG
        self.daily_stats_file = os.path.join(DATA_DIR, "daily_risk_stats.json")
        
        # Инициализация статистики
        self.daily_stats = self._load_daily_stats()
        self.session_loss = 0.0
        self.total_trades = 0
        self.max_drawdown = 0.0
        
    def _load_daily_stats(self) -> Dict:
        """Загрузка дневной статистики рисков"""
        try:
            if os.path.exists(self.daily_stats_file):
                with open(self.daily_stats_file, 'r') as f:
                    stats = json.load(f)
                    
                    # Проверка даты
                    if stats.get('date') == datetime.now().strftime('%Y-%m-%d'):
                        return stats
                    
        except Exception as e:
            logger.warning(f"Error loading daily stats: {e}")
        
        # Новая статистика
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'total_loss': 0.0,
            'total_trades': 0,
            'max_loss_trade': 0.0,
            'consecutive_losses': 0,
            'risk_level': 'NORMAL',
            'daily_limit_exceeded': False
        }
    
    def _save_daily_stats(self):
        """Сохранение дневной статистики"""
        try:
            with open(self.daily_stats_file, 'w') as f:
                json.dump(self.daily_stats, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving daily stats: {e}")
    
    def can_open_position(self, direction: str, spread: float, price: float) -> Tuple[bool, str]:
        """Проверка возможности открытия позиции"""
        logger.debug(f"Risk check: {direction}, spread={spread:.3f}%, price={price:.2f}")
        
        # Проверка дневного лимита убытков
        if self.daily_stats['daily_limit_exceeded']:
            return False, "Daily loss limit exceeded"
        
        current_daily_loss = self.daily_stats['total_loss'] + self.session_loss
        
        if abs(current_daily_loss) >= self.config['MAX_DAILY_LOSS']:
            self.daily_stats['daily_limit_exceeded'] = True
            self._save_daily_stats()
            return False, "Daily loss limit reached"
        
        # Проверка минимального спреда - берем из конфига
        min_spread = self.config.get('MIN_SPREAD_ENTER', 0.0015) * 100
        if spread < min_spread:
            return False, f"Spread too low: {spread:.3f}% < {min_spread:.3f}%"
        
        # Проверка максимального размера позиции
        max_contracts = self.config['MAX_POSITION_CONTRACTS']
        if max_contracts <= 0:
            return False, "Max position size is zero or negative"
        
        # Проверка максимальной стоимости позиции
        position_value = price * max_contracts
        if position_value > self.config['MAX_POSITION_USD']:
            return False, f"Position value ${position_value:.2f} > ${self.config['MAX_POSITION_USD']}"
        
        logger.debug(f"Risk check result: OK")
        return True, "OK"
    
    def calculate_position_size(self, price: float, spread: float) -> Dict:
        """Расчет оптимального размера позиции"""
        
        # Базовая позиция по контрактам
        base_contracts = self.config['MAX_POSITION_CONTRACTS']
        
        # Применение коэффициента безопасности
        safe_contracts = base_contracts * self.config['SAFETY_MULTIPLIER']
        
        # Проверка стоимости
        position_value = price * safe_contracts
        
        # Если стоимость превышает лимит, уменьшаем
        if position_value > self.config['MAX_POSITION_USD']:
            safe_contracts = self.config['MAX_POSITION_USD'] / price
        
        return {
            'contracts': safe_contracts,
            'usd_value': price * safe_contracts,
            'leverage': 1.0,
            'risk_percentage': (self.config['MAX_TRADE_LOSS'] / (price * safe_contracts)) * 100
        }
    
    def record_trade_result(self, pnl: float, trade_volume: float):
        """Запись результата сделки"""
        self.total_trades += 1
        
        if pnl < 0:  # Убыточная сделка
            self.session_loss += pnl
            self.daily_stats['total_loss'] += pnl
            self.daily_stats['consecutive_losses'] += 1
            
            # Обновление максимального убытка за сделку
            if abs(pnl) > self.daily_stats['max_loss_trade']:
                self.daily_stats['max_loss_trade'] = abs(pnl)
                
            # Проверка лимита на сделку
            if abs(pnl) > self.config['MAX_TRADE_LOSS']:
                logger.warning(f"Trade loss exceeded limit: ${abs(pnl):.4f} > ${self.config['MAX_TRADE_LOSS']}")
            
        else:  # Прибыльная сделка
            self.daily_stats['consecutive_losses'] = 0
        
        # Обновление максимальной просадки
        current_drawdown = abs(self.daily_stats['total_loss'])
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
        
        # Проверка дневного лимита
        if abs(self.daily_stats['total_loss']) >= self.config['MAX_DAILY_LOSS']:
            self.daily_stats['daily_limit_exceeded'] = True
            logger.error(f"DAILY LOSS LIMIT REACHED: ${self.daily_stats['total_loss']:.2f}")
        
        self.daily_stats['total_trades'] = self.total_trades
        self._save_daily_stats()
    
    def get_risk_status(self) -> Dict:
        """Получение текущего статуса рисков"""
        return {
            'daily_loss': self.daily_stats['total_loss'],
            'daily_limit_exceeded': self.daily_stats['daily_limit_exceeded'],
            'session_loss': self.session_loss,
            'max_drawdown': self.max_drawdown,
            'consecutive_losses': self.daily_stats['consecutive_losses'],
            'total_trades': self.total_trades,
            'risk_level': self.daily_stats['risk_level']
        }
    
    def reset_daily_stats(self):
        """Сброс дневной статистики (для тестирования)"""
        self.daily_stats = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'total_loss': 0.0,
            'total_trades': 0,
            'max_loss_trade': 0.0,
            'consecutive_losses': 0,
            'risk_level': 'NORMAL',
            'daily_limit_exceeded': False
        }
        self.session_loss = 0.0
        self._save_daily_stats()
        logger.info("Daily stats reset")
    
    async def initialize(self):
        """Инициализация менеджера рисков"""
        logger.info(f"Risk Manager initialized. Daily loss limit: ${self.config['MAX_DAILY_LOSS']}")
        return True