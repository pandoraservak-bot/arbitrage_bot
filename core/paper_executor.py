# Paper-trading исполнение ордеров
import asyncio
import time
import logging
import json
import os
from typing import Dict, List, Optional
from datetime import datetime

from config import DATA_DIR, TRADING_CONFIG

logger = logging.getLogger(__name__)

class PaperTradeExecutor:
    def __init__(self):
        self.config = TRADING_CONFIG
        self.portfolio_file = os.path.join(DATA_DIR, "paper_portfolio.json")
        
        # Состояние портфеля
        self.portfolio = {
            'USDT': 1000.0,  # Начальный депозит
            'NVDA': 0.0,
            'last_updated': datetime.now().isoformat()
        }
        
        # История ордеров
        self.order_history = []
        self.trade_history = []
        
        # Имитация задержек
        self.execution_delay = 0.05  # 50ms задержка исполнения
        
    def _save_portfolio(self):
        """Сохранение состояния портфеля"""
        try:
            self.portfolio['last_updated'] = datetime.now().isoformat()
            with open(self.portfolio_file, 'w') as f:
                json.dump(self.portfolio, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving portfolio: {e}")
    
    def _load_portfolio(self):
        """Загрузка состояния портфеля"""
        try:
            if os.path.exists(self.portfolio_file):
                with open(self.portfolio_file, 'r') as f:
                    self.portfolio = json.load(f)
                logger.info(f"Portfolio loaded: USDT=${self.portfolio.get('USDT', 0):.2f}")
        except Exception as e:
            logger.warning(f"Error loading portfolio: {e}")
    
    def _calculate_fee(self, exchange: str, volume: float) -> float:
        """Расчет комиссии"""
        fee_rate = self.config['FEES'].get(exchange, 0.001)
        return volume * fee_rate
    
    def _simulate_market_price(self, base_price: float, side: str) -> float:
        """Имитация рыночной цены с проскальзыванием"""
        slippage = self.config['MARKET_SLIPPAGE']
        
        if side == 'buy':
            # При покупке платим чуть выше
            return base_price * (1 + slippage)
        else:  # sell
            # При продаже получаем чуть ниже
            return base_price * (1 - slippage)
    
    async def execute_market_order(self, order: Dict) -> Dict:
        """Исполнение рыночного ордера"""
        await asyncio.sleep(self.execution_delay)  # Имитация задержки сети
        
        exchange = order.get('exchange')
        symbol = order.get('symbol')
        side = order.get('side')
        amount = order.get('amount')
        
        # Для простоты используем фиксированные цены (в реальности будут из WebSocket)
        current_prices = {
            'bitget': {'NVDAUSDT': 171.0},
            'hyperliquid': {'xyz:NVDA': 171.0}
        }
        
        base_price = current_prices.get(exchange, {}).get(symbol, 170.0)
        executed_price = self._simulate_market_price(base_price, side)
        
        # Расчет объема
        volume = amount * executed_price
        
        # Расчет комиссии
        fee = self._calculate_fee(exchange, volume)
        
        # Обновление портфеля
        if side == 'buy':
            cost = volume + fee
            if self.portfolio['USDT'] >= cost:
                self.portfolio['USDT'] -= cost
                self.portfolio['NVDA'] += amount
            else:
                return {
                    'success': False,
                    'error': 'Insufficient USDT balance',
                    'order': order
                }
        else:  # sell
            if self.portfolio['NVDA'] >= amount:
                self.portfolio['NVDA'] -= amount
                self.portfolio['USDT'] += volume - fee
            else:
                return {
                    'success': False,
                    'error': 'Insufficient NVDA balance',
                    'order': order
                }
        
        order_result = {
            'success': True,
            'order_id': f"order_{int(time.time() * 1000)}_{len(self.order_history)}",
            'exchange': exchange,
            'symbol': symbol,
            'side': side,
            'amount': amount,
            'executed_amount': amount,
            'price': executed_price,
            'fee': fee,
            'timestamp': time.time(),
            'status': 'filled'
        }
        
        self.order_history.append(order_result)
        self._save_portfolio()
        
        logger.debug(f"Paper order executed: {side} {amount} {symbol} @ {executed_price:.4f}")
        
        return order_result
    
    async def execute_fok_pair(self, buy_order: Dict, sell_order: Dict, tag: str = "") -> Dict:
        """Исполнение пары ордеров FOK (Fill-or-Kill)"""
        # Проверка балансов перед исполнением
        buy_cost = buy_order['amount'] * 171.0  # Оценочная стоимость
        buy_cost_with_fee = buy_cost * (1 + self.config['FEES'][buy_order['exchange']])
        
        if self.portfolio['USDT'] < buy_cost_with_fee:
            return {
                'success': False,
                'error': f'Insufficient USDT for FOK: ${self.portfolio["USDT"]:.2f} < ${buy_cost_with_fee:.2f}',
                'tag': tag
            }
        
        # Исполнение покупки
        buy_result = await self.execute_market_order(buy_order)
        if not buy_result['success']:
            return {
                'success': False,
                'error': f'Buy order failed: {buy_result.get("error")}',
                'tag': tag
            }
        
        # Исполнение продажи
        sell_result = await self.execute_market_order(sell_order)
        if not sell_result['success']:
            # Откат покупки (в реальности это невозможно, но для paper-trading допустимо)
            logger.warning(f"Sell order failed, rolling back buy order (paper-trading only)")
            self.portfolio['USDT'] += buy_result['price'] * buy_result['amount'] + buy_result['fee']
            self.portfolio['NVDA'] -= buy_result['amount']
            
            return {
                'success': False,
                'error': f'Sell order failed: {sell_result.get("error")}',
                'tag': tag
            }
        
        trade_result = {
            'success': True,
            'tag': tag,
            'buy_order': buy_result,
            'sell_order': sell_result,
            'net_effect': {
                'usdt_change': self.portfolio['USDT'] - 1000.0,  # Относительно начального депозита
                'nvda_change': self.portfolio['NVDA'],
                'total_fees': buy_result['fee'] + sell_result['fee']
            }
        }
        
        self.trade_history.append(trade_result)
        logger.info(f"FOK pair executed: {tag}, Fees: ${trade_result['net_effect']['total_fees']:.4f}")
        
        return trade_result
    
    def execute_fok_pair_sync(self, buy_order: Dict, sell_order: Dict, tag: str = "") -> Dict:
        """Синхронная версия исполнения FOK пары"""
        try:
            # Пробуем получить текущий event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если loop запущен, создаем Future и ждем ее
                future = asyncio.run_coroutine_threadsafe(
                    self.execute_fok_pair(buy_order, sell_order, tag),
                    loop
                )
                return future.result(timeout=10)  # Таймаут 10 секунд
            else:
                # Loop не запущен, запускаем новый
                return asyncio.run(self.execute_fok_pair(buy_order, sell_order, tag))
        except RuntimeError:
            # Нет event loop, создаем новый
            return asyncio.run(self.execute_fok_pair(buy_order, sell_order, tag))
    
    def get_portfolio(self) -> Dict:
        """Получение текущего состояния портфеля"""
        return self.portfolio.copy()
    
    def get_portfolio_value(self, current_price: float = 171.0) -> float:
        """Расчет общей стоимости портфеля"""
        return self.portfolio['USDT'] + self.portfolio['NVDA'] * current_price
    
    def get_trade_history(self) -> List[Dict]:
        """Получение истории сделок"""
        return self.trade_history.copy()
    
    def reset_portfolio(self, initial_usdt: float = 1000.0):
        """Сброс портфеля к начальному состоянию"""
        self.portfolio = {
            'USDT': initial_usdt,
            'NVDA': 0.0,
            'last_updated': datetime.now().isoformat()
        }
        self.order_history = []
        self.trade_history = []
        self._save_portfolio()
        logger.info(f"Portfolio reset to USDT=${initial_usdt:.2f}")
    
    async def initialize(self):
        """Инициализация paper executor"""
        self._load_portfolio()
        logger.info(f"Paper Trading initialized. Portfolio: USDT=${self.portfolio['USDT']:.2f}")
        return True