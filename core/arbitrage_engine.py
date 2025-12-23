# core/arbitrage_engine.py
import time
import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from enum import Enum

from config import TRADING_CONFIG

logger = logging.getLogger(__name__)

class TradeDirection(Enum):
    B_TO_H = "B→H"
    H_TO_B = "H→B"

@dataclass
class Position:
    """Класс для представления арбитражной позиции - все спреды ВАЛОВЫЕ БЕЗ КОМИССИЙ"""
    
    id: str
    direction: TradeDirection
    entry_time: float
    contracts: float
    entry_prices: Dict[str, float]  # Цены при входе
    entry_spread: float  # ВАЛОВЫЙ спред при входе (положительный, без комиссий)
    entry_slippage: Dict[str, float]  # Проскальзывание при входе
    
    # Параметры для закрытия
    exit_target: float  # Целевой ВАЛОВЫЙ спред для выхода (чем ниже/отрицательнее, тем лучше)
    
    # Текущее состояние
    status: str = "open"  # open, closed
    current_exit_spread: float = 0.0  # Текущий ВАЛОВЫЙ спред для выхода
    last_spread_update: float = 0.0  # Время последнего обновления спреда
    spread_history: List[float] = field(default_factory=list)  # История валовых спредов
    update_count: int = 0
    
    # Информация о закрытии
    exit_time: Optional[float] = None
    exit_reason: Optional[str] = None
    exit_prices: Optional[Dict[str, float]] = None
    final_pnl: Optional[Dict] = None  # Здесь уже С УЧЕТОМ комиссий
    
    def __post_init__(self):
        """Инициализация после создания"""
        self.last_spread_update = time.time()
        self.spread_history.append(self.entry_spread)
        logger.info(f"📊 Position created: {self.id}, "
                   f"Entry spread (gross): {self.entry_spread:.3f}%, "
                   f"Exit target (gross): {self.exit_target:.3f}%")
    
    def update_exit_spread(self, exit_spread: float):
        """Обновление текущего валового спреда для выхода"""
        self.current_exit_spread = exit_spread
        self.last_spread_update = time.time()
        self.spread_history.append(exit_spread)
        self.update_count += 1
        
        # Детальное логирование при значительных изменениях
        if len(self.spread_history) > 1:
            prev_spread = self.spread_history[-2]
            if abs(exit_spread - prev_spread) > 0.05:  # Изменение более 0.05%
                logger.debug(f"Position {self.id}: exit spread changed from {prev_spread:.3f}% to {exit_spread:.3f}%")
    
    def should_close(self) -> bool:
        """Проверка, нужно ли закрывать позицию (по валовому спреду)
        Закрываем, когда спред выхода станет РАВЕН ИЛИ ВЫШЕ целевого
        (т.е. current_exit_spread >= exit_target) с небольшой погрешностью"""
        
        # Добавляем погрешность 0.001% для учета округлений
        epsilon = 0.001
        return self.current_exit_spread >= (self.exit_target - epsilon)
    
    def get_age_seconds(self) -> float:
        """Возраст позиции в секундах"""
        if self.exit_time:
            return self.exit_time - self.entry_time
        return time.time() - self.entry_time
    
    def get_age_formatted(self) -> str:
        """Возраст позиции в формате ЧЧ:ММ:СС"""
        age = self.get_age_seconds()
        hours = int(age // 3600)
        minutes = int((age % 3600) // 60)
        seconds = int(age % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def get_statistics(self) -> Dict:
        """Получение статистики позиции"""
        stats = {
            'id': self.id,
            'direction': self.direction.value,
            'status': self.status,
            'age_seconds': self.get_age_seconds(),
            'age_formatted': self.get_age_formatted(),
            'contracts': self.contracts,
            'entry_spread_gross': self.entry_spread,  # Явно указываем gross
            'current_exit_spread_gross': self.current_exit_spread,  # Явно указываем gross
            'exit_target_gross': self.exit_target,  # Явно указываем gross
            'spread_updates': self.update_count,
            'should_close': self.should_close(),
            'entry_prices': self.entry_prices,
            'last_update_ago': time.time() - self.last_spread_update,
        }
        
        if self.spread_history:
            stats['max_exit_spread'] = max(self.spread_history)
            stats['min_exit_spread'] = min(self.spread_history)
            stats['avg_exit_spread'] = sum(self.spread_history) / len(self.spread_history)
            if len(self.spread_history) >= 5:
                stats['recent_spreads'] = self.spread_history[-5:]
        
        if self.exit_time:
            stats['exit_time'] = self.exit_time
            stats['exit_reason'] = self.exit_reason
            stats['exit_prices'] = self.exit_prices
            stats['final_pnl_with_fees'] = self.final_pnl  # С комиссиями
        
        return stats

class ArbitrageEngine:
    def __init__(self, risk_manager, paper_executor):
        self.risk_manager = risk_manager
        self.paper_executor = paper_executor
        self.config = TRADING_CONFIG
        
        # Callback для обновления статистики лучших спредов
        self.update_exit_spread_callback = None
        
        # Состояние
        self.open_positions = []
        self.position_counter = 0
        self.trade_history = []
        
        # Статистика
        self.total_fees = 0.0
        self.total_pnl = 0.0
        self.total_volume = 0.0
    
    def set_exit_spread_callback(self, callback):
        """Установка callback для обновления статистики лучших спредов выхода"""
        self.update_exit_spread_callback = callback
    
    def calculate_spreads(self, bitget_data: Dict, hyper_data: Dict, 
                         bitget_slippage: Dict = None, hyper_slippage: Dict = None) -> Dict:
        """Расчет спредов в обе стороны (только для входа) - ВАЛОВЫЙ СПРЕД БЕЗ КОМИССИЙ"""
        if not all([bitget_data, hyper_data]):
            return {}
        
        # Проверяем наличие необходимых полей
        if 'bid' not in bitget_data or 'ask' not in bitget_data:
            return {}
        
        if 'bid' not in hyper_data or 'ask' not in hyper_data:
            return {}
        
        bg_bid = bitget_data['bid']
        bg_ask = bitget_data['ask']
        hl_bid = hyper_data['bid']
        hl_ask = hyper_data['ask']
        
        # Проверка на нулевые цены
        if bg_bid == 0 or bg_ask == 0 or hl_bid == 0 or hl_ask == 0:
            return {}
        
        # Используем расчетное проскальзывание или берем из конфига
        if bitget_slippage:
            bg_buy_slippage = bitget_slippage.get('buy', self.config['MARKET_SLIPPAGE'])
            bg_sell_slippage = bitget_slippage.get('sell', self.config['MARKET_SLIPPAGE'])
        else:
            bg_buy_slippage = self.config['MARKET_SLIPPAGE']
            bg_sell_slippage = self.config['MARKET_SLIPPAGE']
        
        if hyper_slippage:
            hl_buy_slippage = hyper_slippage.get('buy', self.config['MARKET_SLIPPAGE'])
            hl_sell_slippage = hyper_slippage.get('sell', self.config['MARKET_SLIPPAGE'])
        else:
            hl_buy_slippage = self.config['MARKET_SLIPPAGE']
            hl_sell_slippage = self.config['MARKET_SLIPPAGE']
        
        # Спред B→H (покупаем на Bitget, продаем на Hyperliquid) - ТОЛЬКО ВАЛОВЫЙ СПРЕД
        buy_price_bh = bg_ask * (1 + bg_buy_slippage)  # Покупаем на Bitget с проскальзыванием
        sell_price_bh = hl_bid * (1 - hl_sell_slippage)  # Продаем на Hyperliquid с проскальзыванием
        gross_spread_bh = (sell_price_bh / buy_price_bh - 1) * 100  # Положительный = хороший для входа
        
        # Спред H→B (покупаем на Hyperliquid, продаем на Bitget) - ТОЛЬКО ВАЛОВЫЙ СПРЕД
        buy_price_hb = hl_ask * (1 + hl_buy_slippage)  # Покупаем на Hyperliquid с проскальзыванием
        sell_price_hb = bg_bid * (1 - bg_sell_slippage)  # Продаем на Bitget с проскальзыванием
        gross_spread_hb = (sell_price_hb / buy_price_hb - 1) * 100  # Положительный = хороший для входа
        
        return {
            TradeDirection.B_TO_H: {
                'gross_spread': gross_spread_bh,  # Положительный = хороший для входа
                'buy_price': buy_price_bh,
                'sell_price': sell_price_bh,
                'buy_exchange': 'bitget',
                'sell_exchange': 'hyperliquid',
                'slippage_used': {
                    'bitget_buy': bg_buy_slippage,
                    'hyperliquid_sell': hl_sell_slippage
                },
                'raw_prices': {
                    'bitget_ask': bg_ask,
                    'hyperliquid_bid': hl_bid
                }
            },
            TradeDirection.H_TO_B: {
                'gross_spread': gross_spread_hb,  # Положительный = хороший для входа
                'buy_price': buy_price_hb,
                'sell_price': sell_price_hb,
                'buy_exchange': 'hyperliquid',
                'sell_exchange': 'bitget',
                'slippage_used': {
                    'hyperliquid_buy': hl_buy_slippage,
                    'bitget_sell': bg_sell_slippage
                },
                'raw_prices': {
                    'hyperliquid_ask': hl_ask,
                    'bitget_bid': bg_bid
                }
            }
        }
    
    def calculate_exit_spread_for_market(self, bitget_data: Dict, hyper_data: Dict,
                                        bitget_slippage: Dict = None, hyper_slippage: Dict = None) -> Dict:
        """Расчет выходных спредов для рынка (даже без позиций) - ВАЛОВЫЙ СПРЕД БЕЗ КОМИССИЙ"""
        
        if not bitget_data or not hyper_data:
            return {}
        
        # Проверяем наличие необходимых полей
        if 'bid' not in bitget_data or 'ask' not in bitget_data:
            return {}
            
        if 'bid' not in hyper_data or 'ask' not in hyper_data:
            return {}
        
        # Используем расчетное проскальзывание или берем из конфига
        if bitget_slippage:
            bg_buy_slippage = bitget_slippage.get('buy', self.config['MARKET_SLIPPAGE'])
            bg_sell_slippage = bitget_slippage.get('sell', self.config['MARKET_SLIPPAGE'])
        else:
            bg_buy_slippage = self.config['MARKET_SLIPPAGE']
            bg_sell_slippage = self.config['MARKET_SLIPPAGE']
        
        if hyper_slippage:
            hl_buy_slippage = hyper_slippage.get('buy', self.config['MARKET_SLIPPAGE'])
            hl_sell_slippage = hyper_slippage.get('sell', self.config['MARKET_SLIPPAGE'])
        else:
            hl_buy_slippage = self.config['MARKET_SLIPPAGE']
            hl_sell_slippage = self.config['MARKET_SLIPPAGE']
        
        # Выходной спред для B→H позиции (покупаем на Hyper, продаем на Bitget)
        exit_buy_price_bh = hyper_data['ask'] * (1 + hl_buy_slippage)
        exit_sell_price_bh = bitget_data['bid'] * (1 - bg_sell_slippage)
        
        # Выходной спред для H→B позиции (покупаем на Bitget, продаем на Hyper)
        exit_buy_price_hb = bitget_data['ask'] * (1 + bg_buy_slippage)
        exit_sell_price_hb = hyper_data['bid'] * (1 - hl_sell_slippage)
        
        # Рассчитываем валовые спреды (БЕЗ КОМИССИЙ)
        exit_spread_bh = 0.0
        exit_spread_hb = 0.0
        
        if exit_buy_price_bh > 0:
            exit_spread_bh = (exit_sell_price_bh / exit_buy_price_bh - 1) * 100
        
        if exit_buy_price_hb > 0:
            exit_spread_hb = (exit_sell_price_hb / exit_buy_price_hb - 1) * 100
        
        return {
            TradeDirection.B_TO_H: exit_spread_bh,
            TradeDirection.H_TO_B: exit_spread_hb
        }
    
    def calculate_exit_spread(self, position: Position, bitget_data: Dict, hyper_data: Dict,
                             bitget_slippage: Dict = None, hyper_slippage: Dict = None) -> float:
        """Расчет спреда для закрытия позиции - ВАЛОВЫЙ СПРЕД БЕЗ КОМИССИЙ"""
        
        # Защита от отсутствия данных
        if not bitget_data or not hyper_data:
            logger.debug("❌ Missing market data")
            return position.current_exit_spread  # Возвращаем предыдущее значение
        
        # Проверяем наличие необходимых полей
        if 'bid' not in bitget_data or 'ask' not in bitget_data:
            logger.debug("❌ Bitget missing bid/ask")
            return position.current_exit_spread
        
        if 'bid' not in hyper_data or 'ask' not in hyper_data:
            logger.debug("❌ Hyperliquid missing bid/ask")
            return position.current_exit_spread
        
        # Используем расчетное проскальзывание или берем из конфига
        if bitget_slippage:
            bg_buy_slippage = bitget_slippage.get('buy', self.config['MARKET_SLIPPAGE'])
            bg_sell_slippage = bitget_slippage.get('sell', self.config['MARKET_SLIPPAGE'])
        else:
            bg_buy_slippage = self.config['MARKET_SLIPPAGE']
            bg_sell_slippage = self.config['MARKET_SLIPPAGE']
        
        if hyper_slippage:
            hl_buy_slippage = hyper_slippage.get('buy', self.config['MARKET_SLIPPAGE'])
            hl_sell_slippage = hyper_slippage.get('sell', self.config['MARKET_SLIPPAGE'])
        else:
            hl_buy_slippage = self.config['MARKET_SLIPPAGE']
            hl_sell_slippage = self.config['MARKET_SLIPPAGE']
        
        # Рассчитываем спред для выхода в зависимости от направления позиции
        if position.direction == TradeDirection.B_TO_H:
            # Для закрытия B→H позиции: покупаем на Hyperliquid, продаем на Bitget
            exit_buy_price = hyper_data['ask'] * (1 + hl_buy_slippage)
            exit_sell_price = bitget_data['bid'] * (1 - bg_sell_slippage)
            
        else:  # H→B
            # Для закрытия H→B позиции: покупаем на Bitget, продаем на Hyperliquid
            exit_buy_price = bitget_data['ask'] * (1 + bg_buy_slippage)
            exit_sell_price = hyper_data['bid'] * (1 - hl_sell_slippage)
        
        # Рассчитываем валовый спред (БЕЗ КОМИССИЙ)
        if exit_buy_price > 0:
            exit_gross_spread = (exit_sell_price / exit_buy_price - 1) * 100
        else:
            exit_gross_spread = 0.0
        
        return exit_gross_spread
    
    def find_opportunity(self, bitget_data: Dict, hyper_data: Dict,
                        bitget_slippage: Dict = None, hyper_slippage: Dict = None) -> Optional[Tuple[TradeDirection, Dict]]:
        """Поиск арбитражной возможности для входа с учетом реального проскальзывания (БЕЗ КОМИССИЙ)"""
        if self.open_positions:
            logger.debug("🔄 Already have open positions, skipping opportunity search")
            return None
        
        # Рассчитываем спреды с учетом реального проскальзывания (БЕЗ КОМИССИЙ)
        spreads = self.calculate_spreads(bitget_data, hyper_data, bitget_slippage, hyper_slippage)
        
        if not spreads:
            logger.debug("❌ No spreads calculated - missing market data")
            return None
        
        # MIN_SPREAD_ENTER теперь относится к валовому спреду (без комиссий)
        min_spread_required = self.config['MIN_SPREAD_ENTER'] * 100
        # Убрали spam - логируем только при нахождении возможности
        
        for direction, data in spreads.items():
            # Используем валовый спред без комиссий
            gross_spread = data['gross_spread']
            
            # Убрали spam - не логируем каждую проверку
            
            if gross_spread >= min_spread_required:
                risk_ok, reason = self.risk_manager.can_open_position(
                    direction, gross_spread, data['buy_price']
                )
                if risk_ok:
                    logger.info(f"✅ Opportunity FOUND: {direction.value}, spread: {gross_spread:.3f}% - READY TO EXECUTE!")
                    return direction, data
                else:
                    logger.warning(f"⚠️ Risk check FAILED for {direction.value}: {reason}")
            else:
                logger.debug(f"📉 Spread too low for {direction.value}: {gross_spread:.3f}% < {min_spread_required:.3f}%")
        
        logger.debug("🔍 No suitable opportunities found in this cycle")
        return None
    
    async def execute_opportunity(self, opportunity: Tuple[TradeDirection, Dict]) -> bool:
        """Исполнение арбитражной возможности с учетом проскальзывания"""
        direction, spread_data = opportunity
        
        # Расчет размера позиции
        position_size = self.risk_manager.calculate_position_size(
            spread_data['buy_price'], 
            spread_data['gross_spread']
        )
        
        if position_size['contracts'] <= 0:
            return False
        
        # Подготовка ордеров FOK
        buy_order = {
            'exchange': spread_data['buy_exchange'],
            'symbol': 'NVDAUSDT' if spread_data['buy_exchange'] == 'bitget' else 'xyz:NVDA',
            'side': 'buy',
            'type': 'market',
            'amount': position_size['contracts'],
            'time_in_force': 'FOK',
            'estimated_slippage': spread_data['slippage_used'].get(f"{spread_data['buy_exchange']}_buy", 0.0001)
        }
        
        sell_order = {
            'exchange': spread_data['sell_exchange'],
            'symbol': 'xyz:NVDA' if spread_data['sell_exchange'] == 'hyperliquid' else 'NVDAUSDT',
            'side': 'sell',
            'type': 'market',
            'amount': position_size['contracts'],
            'time_in_force': 'FOK',
            'estimated_slippage': spread_data['slippage_used'].get(f"{spread_data['sell_exchange']}_sell", 0.0001)
        }
        
        # Исполнение
        logger.info(f"Attempting to execute FOK pair: buy on {spread_data['buy_exchange']}, sell on {spread_data['sell_exchange']}")
        entry_result = await self.paper_executor.execute_fok_pair(
            buy_order, sell_order, f"entry_{direction.value}"
        )
        
        if not entry_result.get('success', False):
            error_msg = entry_result.get('error', 'Unknown error')
            logger.error(f"❌ FOK entry FAILED: {error_msg}")
            logger.error(f"   Response: {entry_result}")
            return False
        
        # Создание позиции с учетом проскальзывания
        position = Position(
            id=f"pos_{self.position_counter:06d}",
            direction=direction,
            entry_time=time.time(),
            contracts=position_size['contracts'],
            entry_prices={
                'buy': spread_data['buy_price'],
                'sell': spread_data['sell_price']
            },
            entry_spread=spread_data['gross_spread'],
            entry_slippage=spread_data['slippage_used'],
            exit_target=self.config['MIN_SPREAD_EXIT'] * 100
        )
        
        self.open_positions.append(position)
        self.position_counter += 1
        self.total_volume += position_size['contracts'] * spread_data['buy_price']
        
        logger.info(f"✅ Position opened: {position.id}, "
                   f"Direction: {direction.value}, "
                   f"Gross spread: {spread_data['gross_spread']:.3f}%, "
                   f"Slippage: {spread_data['slippage_used']}")
        
        return True
    
    def monitor_positions(self, bitget_data: Dict, hyper_data: Dict,
                         bitget_slippage: Dict = None, hyper_slippage: Dict = None):
        """Мониторинг и закрытие позиций по условиям (только валовый спред)"""
        current_time = time.time()
        
        # Создаем копию списка для безопасной итерации
        positions_to_check = self.open_positions.copy()
        
        for position in positions_to_check:
            # Проверяем, что позиция все еще открыта
            if position.status != 'open' or position not in self.open_positions:
                continue
            
            # Проверка времени удержания (только для логирования)
            hold_time = current_time - position.entry_time
            if hold_time > self.config['MAX_HOLD_TIME']:
                logger.warning(f"Position {position.id} exceeded max hold time: {hold_time:.1f}s")
                # Не закрываем принудительно, только логируем
            
            # Расчет текущего спреда для выхода (ВАЛОВЫЙ БЕЗ КОМИССИЙ)
            current_spread = self.calculate_exit_spread(position, bitget_data, hyper_data,
                                                       bitget_slippage, hyper_slippage)
            
            # Обновляем состояние позиции
            position.update_exit_spread(current_spread)
            
            # Логируем детальное состояние
            if position.update_count % 10 == 0:  # Каждые 10 обновлений
                logger.debug(f"Position {position.id}: exit_spread={current_spread:.3f}%, "
                            f"target={position.exit_target:.3f}%, hold_time={hold_time:.1f}s")
            
            # Закрытие по целевому спреду (выходной валовый спред >= целевого)
            # exit_target отрицательный (например -0.05%), но для выхода нужен спред >= этого значения
            if position.should_close():
                logger.info(f"🚀 Closing position {position.id}: "
                           f"Exit spread {current_spread:.3f}% >= target {position.exit_target:.3f}%")
                self.close_position(position, current_spread, 
                                  f"Exit spread reached: {current_spread:.3f}% >= {position.exit_target:.3f}%")
    
    def close_position(self, position: Position, exit_spread: float, reason: str):
        """Закрытие позиции"""
        # Проверяем, что позиция еще не закрыта
        if position.status != 'open':
            logger.warning(f"Position {position.id} already closed, skipping")
            return
        
        # Определение ордеров для закрытия
        if position.direction == TradeDirection.B_TO_H:
            sell_order = {'exchange': 'bitget', 'side': 'sell', 'amount': position.contracts}
            buy_order = {'exchange': 'hyperliquid', 'side': 'buy', 'amount': position.contracts}
        else:
            sell_order = {'exchange': 'hyperliquid', 'side': 'sell', 'amount': position.contracts}
            buy_order = {'exchange': 'bitget', 'side': 'buy', 'amount': position.contracts}
        
        # Исполнение закрытия
        exit_result = self.paper_executor.execute_fok_pair_sync(
            buy_order, sell_order, f"exit_{position.id}"
        )
        
        if not exit_result['success']:
            logger.error(f"Failed to close position {position.id}: {exit_result.get('error')}")
            return
        
        # Вызываем callback для обновления статистики лучших спредов выхода
        if self.update_exit_spread_callback:
            self.update_exit_spread_callback(exit_spread, position.direction, position.id, True)
        
        # Расчет PnL С УЧЕТОМ КОМИССИЙ
        pnl_data = self.calculate_trade_pnl(position, exit_result)
        
        # Обновление позиции
        position.status = 'closed'
        position.exit_time = time.time()
        position.exit_reason = reason
        position.exit_prices = {
            'buy': exit_result['buy_order']['price'],
            'sell': exit_result['sell_order']['price']
        }
        position.final_pnl = pnl_data
        
        # Удаляем позицию из открытых
        try:
            self.open_positions.remove(position)
        except ValueError:
            logger.warning(f"Position {position.id} not found in open positions list")
        
        # Добавляем в историю
        self.trade_history.append(position)
        
        # Обновление статистики
        self.total_fees += pnl_data['fees']
        self.total_pnl += pnl_data['net']
        
        logger.info(f"📤 Position closed: {position.id}, "
                   f"Reason: {reason}, "
                   f"Gross PnL: ${pnl_data['gross']:.4f}, "
                   f"Fees: ${pnl_data['fees']:.4f}, "
                   f"Net PnL: ${pnl_data['net']:.4f}")
    
    def force_close_position(self, position: Position, reason: str):
        """Принудительное закрытие позиции"""
        logger.warning(f"⚠️ Force closing position {position.id}: {reason}")
        
        # Рассчитываем текущий спред перед закрытием
        current_spread = position.current_exit_spread
        self.close_position(position, current_spread, f"FORCE: {reason}")
    
    def close_all_positions(self, reason: str = "System shutdown"):
        """Закрытие всех открытых позиций"""
        for position in self.open_positions[:]:
            self.force_close_position(position, reason)
    
    def calculate_trade_pnl(self, position: Position, exit_result: Dict) -> Dict:
        """Расчет PnL сделки С УЧЕТОМ КОМИССИЙ (комиссии только здесь!)"""
        
        entry_buy_price = position.entry_prices['buy']
        entry_sell_price = position.entry_prices['sell']
        contracts = position.contracts
        
        exit_buy_price = exit_result['buy_order']['price']
        exit_sell_price = exit_result['sell_order']['price']
        
        # 1. ВАЛОВАЯ прибыль (без комиссий)
        entry_leg = (entry_sell_price - entry_buy_price) * contracts
        exit_leg = (exit_sell_price - exit_buy_price) * contracts
        gross_pnl = entry_leg + exit_leg
        
        # 2. РАСЧЕТ КОМИССИЙ (4 ордера)
        fees_config = self.config['FEES']
        
        if position.direction == TradeDirection.B_TO_H:
            # Вход: buy Bitget, sell Hyperliquid
            # Выход: buy Hyperliquid, sell Bitget
            entry_buy_fee = entry_buy_price * contracts * fees_config['bitget']
            entry_sell_fee = entry_sell_price * contracts * fees_config['hyperliquid']
            exit_buy_fee = exit_buy_price * contracts * fees_config['hyperliquid']
            exit_sell_fee = exit_sell_price * contracts * fees_config['bitget']
        else:  # H→B
            # Вход: buy Hyperliquid, sell Bitget
            # Выход: buy Bitget, sell Hyperliquid
            entry_buy_fee = entry_buy_price * contracts * fees_config['hyperliquid']
            entry_sell_fee = entry_sell_price * contracts * fees_config['bitget']
            exit_buy_fee = exit_buy_price * contracts * fees_config['bitget']
            exit_sell_fee = exit_sell_price * contracts * fees_config['hyperliquid']
        
        total_fees = entry_buy_fee + entry_sell_fee + exit_buy_fee + exit_sell_fee
        net_pnl = gross_pnl - total_fees
        
        if entry_buy_price * contracts > 0:
            return_percent = (net_pnl / (entry_buy_price * contracts)) * 100
        else:
            return_percent = 0.0
        
        return {
            'gross': gross_pnl,
            'fees': total_fees,
            'net': net_pnl,
            'return_percent': return_percent,
            'fee_breakdown': {
                'entry_buy': entry_buy_fee,
                'entry_sell': entry_sell_fee,
                'exit_buy': exit_buy_fee,
                'exit_sell': exit_sell_fee
            },
            'trade_summary': {
                'direction': position.direction.value,
                'contracts': contracts,
                'entry_cost': entry_buy_price * contracts,
                'gross_return_percent': (gross_pnl / (entry_buy_price * contracts)) * 100 if entry_buy_price * contracts > 0 else 0
            }
        }
    
    def has_open_positions(self) -> bool:
        """Проверка наличия открытых позиций"""
        return any(pos.status == 'open' for pos in self.open_positions)
    
    def get_open_positions(self) -> List[Position]:
        """Получение списка действительно открытых позиций"""
        return [pos for pos in self.open_positions if pos.status == 'open']
    
    def get_statistics(self) -> Dict:
        """Получение статистики движка"""
        open_positions = self.get_open_positions()
        return {
            'open_positions': len(open_positions),
            'total_trades': len(self.trade_history),
            'total_pnl': self.total_pnl,
            'total_fees': self.total_fees,
            'total_volume': self.total_volume,
        }
    
    def diagnose_positions(self) -> Dict:
        """Диагностика состояния всех позиций"""
        open_positions = self.get_open_positions()
        diagnosis = {
            'total_positions': len(open_positions) + len(self.trade_history),
            'open_positions': len(open_positions),
            'closed_positions': len(self.trade_history),
            'positions_detailed': [],
            'issues': []
        }
        
        # Диагностика открытых позиций
        for pos in open_positions:
            pos_data = {
                'id': pos.id,
                'direction': pos.direction.value,
                'age': pos.get_age_formatted(),
                'age_seconds': pos.get_age_seconds(),
                'entry_spread': pos.entry_spread,
                'current_exit_spread': pos.current_exit_spread,
                'exit_target': pos.exit_target,
                'should_close': pos.should_close(),
                'spread_updates': pos.update_count,
                'last_update_seconds': time.time() - pos.last_spread_update,
                'spread_history_count': len(pos.spread_history),
            }
            
            # Проверяем проблемы
            issues = []
            
            # 1. Позиция слишком старая
            if pos.get_age_seconds() > 3600:  # Более часа
                issues.append(f"Position too old: {pos.get_age_formatted()}")
            
            # 2. Спред давно не обновлялся
            if time.time() - pos.last_spread_update > 60:  # Более минута
                issues.append(f"Spread not updated for {time.time() - pos.last_spread_update:.0f}s")
            
            # 3. Позиция должна закрыться, но не закрывается
            if pos.should_close():
                issues.append(f"Should close (exit_spread={pos.current_exit_spread:.3f}% >= target={pos.exit_target:.3f}%)")
            
            # 4. Мало обновлений спреда
            if pos.update_count < 5 and pos.get_age_seconds() > 300:  # 5 минут
                issues.append(f"Few spread updates: {pos.update_count} in {pos.get_age_formatted()}")
            
            if issues:
                pos_data['issues'] = issues
                diagnosis['issues'].extend([f"{pos.id}: {issue}" for issue in issues])
            
            diagnosis['positions_detailed'].append(pos_data)
        
        return diagnosis
    
    def log_diagnosis(self):
        """Логирование диагностической информации"""
        diagnosis = self.diagnose_positions()
        
        logger.info("=" * 60)
        logger.info("POSITION DIAGNOSIS")
        logger.info(f"Open positions: {diagnosis['open_positions']}")
        logger.info(f"Closed positions: {diagnosis['closed_positions']}")
        
        if diagnosis['issues']:
            logger.warning("ISSUES FOUND:")
            for issue in diagnosis['issues']:
                logger.warning(f"  - {issue}")
        
        for pos in diagnosis['positions_detailed']:
            logger.info(f"Position {pos['id']}:")
            logger.info(f"  Direction: {pos['direction']}, Age: {pos['age']}")
            logger.info(f"  Entry spread: {pos['entry_spread']:.3f}%, Current exit: {pos['current_exit_spread']:.3f}%")
            logger.info(f"  Target: {pos['exit_target']:.3f}%, Should close: {pos['should_close']}")
            logger.info(f"  Spread updates: {pos['spread_updates']}, Last update: {pos['last_update_seconds']:.0f}s ago")
            
            if 'issues' in pos and pos['issues']:
                for issue in pos['issues']:
                    logger.warning(f"  ! {issue}")
        
        logger.info("=" * 60)
    
    async def initialize(self):
        """Инициализация движка"""
        logger.info("Arbitrage Engine initialized")
        return True