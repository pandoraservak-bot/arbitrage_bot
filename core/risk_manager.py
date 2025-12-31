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
    
    def can_open_position(self, direction: str, spread: float, price: float, 
                          current_position_contracts: float = 0.0, slippage: float = 0.0) -> Tuple[bool, str]:
        """Проверка возможности открытия позиции
        
        Args:
            direction: направление сделки
            spread: текущий спред
            price: цена входа
            current_position_contracts: текущий размер открытой позиции в контрактах
            slippage: ожидаемое проскальзывание (в долях, например 0.001 = 0.1%)
        """
        # Проверка дневного лимита убытков
        if self.daily_stats['daily_limit_exceeded']:
            logger.warning(f"❌ Daily loss limit exceeded")
            return False, "Daily loss limit exceeded"
        
        current_daily_loss = self.daily_stats['total_loss'] + self.session_loss
        
        if abs(current_daily_loss) >= self.config['MAX_DAILY_LOSS']:
            self.daily_stats['daily_limit_exceeded'] = True
            self._save_daily_stats()
            logger.warning(f"❌ Daily loss limit reached: ${abs(current_daily_loss):.2f} >= ${self.config['MAX_DAILY_LOSS']}")
            return False, "Daily loss limit reached"
        
        # Проверка минимального спреда
        from config import TRADING_CONFIG
        min_spread_from_config = TRADING_CONFIG['MIN_SPREAD_ENTER']
        min_spread_percent = min_spread_from_config * 100
        
        if spread < min_spread_percent:
            logger.warning(f"❌ Spread too low: {spread:.3f}% < {min_spread_percent:.3f}%")
            return False, f"Spread too low: {spread:.3f}% < {min_spread_percent:.3f}%"
        
        # Проверка максимального размера позиции
        max_contracts = self.config['MAX_POSITION_CONTRACTS']
        if max_contracts <= 0:
            logger.warning(f"❌ Max position size is zero or negative: {max_contracts}")
            return False, "Max position size is zero or negative"
        
        # Проверка что не превышаем максимальный размер позиции
        if current_position_contracts >= max_contracts:
            logger.warning(f"❌ Max position reached: {current_position_contracts:.4f} >= {max_contracts:.4f} contracts")
            return False, f"Max position reached: {current_position_contracts:.4f} >= {max_contracts:.4f} contracts"
        
        # Проверка минимального размера ордера
        min_order = self.config.get('MIN_ORDER_CONTRACTS', 0.01)
        if (current_position_contracts + min_order) > max_contracts + 0.0001: # небольшая погрешность
            logger.warning(f"❌ No capacity for even minimal order: {current_position_contracts:.4f} + {min_order} > {max_contracts:.4f}")
            return False, f"No capacity for minimal order"
        
        # Проверка проскальзывания
        max_slippage = self.config.get('MAX_SLIPPAGE', 0.001)
        if slippage > max_slippage:
            msg = f"Slippage too high: {slippage*100:.3f}% > {max_slippage*100:.3f}%"
            logger.warning(f"❌ {msg}")
            return False, msg
        
        return True, "OK"
    
    def check_slippage(self, slippage: float) -> Tuple[bool, str]:
        """Проверка проскальзывания перед входом
        
        Args:
            slippage: ожидаемое проскальзывание (в долях, например 0.001 = 0.1%)
            
        Returns:
            (passed, message) - прошла ли проверка и сообщение
        """
        max_slippage = self.config.get('MAX_SLIPPAGE', 0.001)
        if slippage > max_slippage:
            msg = f"Slippage {slippage*100:.3f}% exceeds max {max_slippage*100:.3f}%"
            return False, msg
        return True, "OK"
    
    def calculate_position_size(self, price: float, spread: float, 
                                current_position_contracts: float = 0.0) -> Dict:
        """Расчет размера ордера для частичного входа в позицию
        
        Args:
            price: цена входа
            spread: текущий спред
            current_position_contracts: текущий размер открытой позиции
            
        Returns:
            Dict с размером ордера и USD стоимостью
        """
        max_contracts = self.config['MAX_POSITION_CONTRACTS']
        min_order = self.config.get('MIN_ORDER_CONTRACTS', 0.01)
        
        # Сколько еще можем добавить
        remaining_capacity = max_contracts - current_position_contracts
        
        if remaining_capacity <= 0:
            return {
                'contracts': 0,
                'usd_value': 0,
                'can_add': False,
                'reason': 'Max position reached'
            }
        
        # Размер ордера = минимальный ордер (частичный вход)
        order_contracts = min(min_order, remaining_capacity)
        
        # Применяем коэффициент безопасности если нужно
        safe_contracts = order_contracts * self.config.get('SAFETY_MULTIPLIER', 1.0)
        
        # Минимум - минимальный ордер
        if safe_contracts < min_order and remaining_capacity >= min_order:
            safe_contracts = min_order
        
        return {
            'contracts': safe_contracts,
            'usd_value': price * safe_contracts,
            'can_add': True,
            'remaining_capacity': remaining_capacity,
            'max_position': max_contracts
        }
    
    def calculate_exit_size(self, position_contracts: float) -> Dict:
        """Расчет размера ордера для частичного выхода из позиции
        
        Args:
            position_contracts: текущий размер позиции в контрактах
            
        Returns:
            Dict с размером ордера для выхода
        """
        min_order = self.config.get('MIN_ORDER_CONTRACTS', 0.01)
        
        if position_contracts <= 0:
            return {
                'contracts': 0,
                'can_exit': False,
                'reason': 'No position to exit'
            }
        
        # Выходим минимальным размером ордера
        exit_contracts = min(min_order, position_contracts)
        
        return {
            'contracts': exit_contracts,
            'can_exit': True,
            'remaining_position': position_contracts - exit_contracts,
            'full_exit': position_contracts <= min_order
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