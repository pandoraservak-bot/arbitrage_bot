# core/arbitrage_engine.py
import time
import logging
import json
import os
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime

from config import TRADING_CONFIG, DATA_DIR

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
    
    def to_dict(self) -> Dict:
        """Сериализация позиции в словарь для сохранения"""
        return {
            'id': self.id,
            'direction': self.direction.value,
            'entry_time': self.entry_time,
            'contracts': self.contracts,
            'entry_prices': self.entry_prices,
            'entry_spread': self.entry_spread,
            'entry_slippage': self.entry_slippage,
            'exit_target': self.exit_target,
            'status': self.status,
            'current_exit_spread': self.current_exit_spread,
            'last_spread_update': self.last_spread_update,
            'spread_history': self.spread_history,
            'update_count': self.update_count,
            'exit_time': self.exit_time,
            'exit_reason': self.exit_reason,
            'exit_prices': self.exit_prices,
            'final_pnl': self.final_pnl,
        }
    
    @staticmethod
    def _parse_direction(direction_value: object) -> TradeDirection:
        if isinstance(direction_value, TradeDirection):
            return direction_value

        direction_str = str(direction_value or "").strip()

        # Поддержка нескольких форматов (на случай старых файлов)
        normalized = direction_str.replace(" ", "").upper()
        if direction_str in {"B→H", "B->H", "B_TO_H", "B2H"} or normalized in {"B→H", "B->H", "B_TO_H", "B2H"}:
            return TradeDirection.B_TO_H
        if direction_str in {"H→B", "H->B", "H_TO_B", "H2B"} or normalized in {"H→B", "H->B", "H_TO_B", "H2B"}:
            return TradeDirection.H_TO_B

        # Последний шанс: эвристика по наличию букв
        if "B" in normalized and "H" in normalized:
            b_index = normalized.find("B")
            h_index = normalized.find("H")
            if 0 <= b_index < h_index:
                return TradeDirection.B_TO_H
            if 0 <= h_index < b_index:
                return TradeDirection.H_TO_B

        logger.warning(f"Unknown direction value in saved position: {direction_value!r}. Defaulting to H→B")
        return TradeDirection.H_TO_B

    @classmethod
    def from_dict(cls, data: Dict) -> 'Position':
        """Десериализация позиции из словаря.

        Должна быть устойчивой к частично заполненным/старым форматам positions.json.
        """

        if not isinstance(data, dict):
            raise TypeError(f"Position.from_dict expected dict, got {type(data)}")

        direction = cls._parse_direction(data.get('direction'))

        entry_time = data.get('entry_time', time.time())
        try:
            entry_time = float(entry_time)
        except Exception:
            entry_time = time.time()

        entry_spread = data.get('entry_spread', 0.0)
        try:
            entry_spread = float(entry_spread)
        except Exception:
            entry_spread = 0.0

        exit_target = data.get('exit_target', 0.0)
        try:
            exit_target = float(exit_target)
        except Exception:
            exit_target = 0.0

        spread_history = data.get('spread_history')
        if not isinstance(spread_history, list) or not spread_history:
            spread_history = [entry_spread]

        current_exit_spread = data.get('current_exit_spread')
        if current_exit_spread is None:
            # В старых форматах мог не сохраняться текущий выходной спред.
            # Выбираем безопасное значение, чтобы позиция не закрылась "сама" до первого обновления рынка.
            if isinstance(spread_history, list) and len(spread_history) > 1:
                current_exit_spread = spread_history[-1]
            else:
                current_exit_spread = exit_target - 1.0
        try:
            current_exit_spread = float(current_exit_spread)
        except Exception:
            current_exit_spread = exit_target - 1.0

        last_spread_update = data.get('last_spread_update')
        if last_spread_update is None:
            last_spread_update = time.time()
        try:
            last_spread_update = float(last_spread_update)
        except Exception:
            last_spread_update = time.time()

        update_count = data.get('update_count')
        if update_count is None:
            update_count = max(len(spread_history) - 1, 0)
        try:
            update_count = int(update_count)
        except Exception:
            update_count = 0

        # Создаем позицию без вызова __post_init__
        position = cls.__new__(cls)
        position.id = str(data.get('id', ''))
        position.direction = direction
        position.entry_time = entry_time
        try:
            position.contracts = float(data.get('contracts', 0.0) or 0.0)
        except Exception:
            position.contracts = 0.0
        position.entry_prices = data.get('entry_prices') or {}
        position.entry_spread = entry_spread
        position.entry_slippage = data.get('entry_slippage') or {}
        position.exit_target = exit_target
        position.status = str(data.get('status', 'open') or 'open').lower()
        position.current_exit_spread = current_exit_spread
        position.last_spread_update = last_spread_update
        position.spread_history = spread_history
        position.update_count = update_count
        position.exit_time = data.get('exit_time')
        position.exit_reason = data.get('exit_reason')
        position.exit_prices = data.get('exit_prices')
        position.final_pnl = data.get('final_pnl')

        return position

class ArbitrageEngine:
    def __init__(self, risk_manager, paper_executor, bot=None):
        self.risk_manager = risk_manager
        self.paper_executor = paper_executor
        self.bot = bot  # Ссылка на NVDAFuturesArbitrageBot для доступа к best_spreads_session
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
        
        # Контроль интервала между ордерами
        self.last_order_time = 0.0
        
        # Путь к файлу с позициями
        self.positions_file = os.path.join(DATA_DIR, "positions.json")
    
    def set_exit_spread_callback(self, callback):
        """Установка callback для обновления статистики лучших спредов выхода"""
        self.update_exit_spread_callback = callback
    
    def _save_positions(self):
        """Сохранение открытых позиций в файл"""
        try:
            positions_data = {
                'positions': [pos.to_dict() for pos in self.open_positions if pos.status == 'open'],
                'position_counter': self.position_counter,
                'last_saved': datetime.now().isoformat()
            }
            
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(self.positions_file, 'w') as f:
                json.dump(positions_data, f, indent=2)
            
            logger.debug(f"Saved {len(positions_data['positions'])} open position(s) to {self.positions_file}")
        except Exception as e:
            logger.error(f"Error saving positions: {e}")
    
    def _load_positions(self):
        """Загрузка открытых позиций из файла."""
        try:
            if not os.path.exists(self.positions_file):
                logger.info("No saved positions file found - starting fresh")
                return

            with open(self.positions_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)

            # Поддержка нескольких форматов файла
            if isinstance(raw, list):
                positions_data = {'positions': raw}
            elif isinstance(raw, dict):
                if 'positions' in raw:
                    positions_data = raw
                # старый формат: один объект позиции без обертки
                elif {'id', 'direction', 'entry_time'}.issubset(set(raw.keys())):
                    positions_data = {'positions': [raw]}
                else:
                    positions_data = raw
            else:
                logger.error(f"Unexpected positions file format: {type(raw)}")
                return

            raw_positions = positions_data.get('positions', [])
            if not isinstance(raw_positions, list):
                logger.error(f"Invalid positions list in {self.positions_file}: {type(raw_positions)}")
                return

            restored_positions: List[Position] = []
            for pos_dict in raw_positions:
                try:
                    if not isinstance(pos_dict, dict):
                        logger.error(f"Invalid position entry in {self.positions_file}: {type(pos_dict)}")
                        continue

                    if str(pos_dict.get('status', 'open')).lower() != 'open':
                        continue

                    position = Position.from_dict(pos_dict)
                    if str(position.status).lower() != 'open':
                        continue

                    restored_positions.append(position)

                    logger.info(
                        f"✅ Restored position: {position.id}, "
                        f"Direction: {position.direction.value}, "
                        f"Contracts: {position.contracts}, "
                        f"Age: {position.get_age_formatted()}, "
                        f"Entry spread: {position.entry_spread:.3f}%, "
                        f"Current exit spread: {position.current_exit_spread:.3f}%, "
                        f"Spread history: {len(position.spread_history)}"
                    )
                except Exception as e:
                    logger.error(f"Error restoring position from {pos_dict}: {e}", exc_info=True)

            self.open_positions = restored_positions

            # Восстанавливаем счетчик позиций
            counter = positions_data.get('position_counter')
            try:
                counter_int = int(counter) if counter is not None else None
            except Exception:
                counter_int = None

            if counter_int is not None:
                self.position_counter = counter_int
            else:
                max_id = -1
                for pos in restored_positions:
                    try:
                        if pos.id.startswith('pos_'):
                            max_id = max(max_id, int(pos.id.split('_', 1)[1]))
                    except Exception:
                        continue
                self.position_counter = max_id + 1 if max_id >= 0 else len(restored_positions)

            if restored_positions:
                logger.info(f"🔄 Restored {len(restored_positions)} open position(s) from previous session")
                logger.info(f"   Last saved: {positions_data.get('last_saved', 'unknown')}")

                # Синхронизация/валидация портфеля (paper trading)
                reconcile = getattr(self.paper_executor, 'reconcile_with_positions', None)
                if callable(reconcile):
                    try:
                        reconcile(restored_positions)
                    except Exception as e:
                        logger.warning(f"Portfolio reconcile failed: {e}", exc_info=True)
            else:
                logger.info(f"Positions file loaded ({self.positions_file}) - no open positions to restore")

        except json.JSONDecodeError as e:
            logger.error(f"Positions file is corrupted (JSON decode): {self.positions_file}: {e}")
        except Exception as e:
            logger.error(f"Error loading positions: {e}", exc_info=True)
    
    def calculate_spreads(self, bitget_data: Dict, hyper_data: Dict,
                         bitget_slippage: Dict = None, hyper_slippage: Dict = None) -> Dict:
        """Расчет спредов в обе стороны (только для входа) - ВАЛОВЫЙ СПРЕД БЕЗ КОМИССИЙ"""
        logger.debug(
            "calculate_spreads() called: has_bitget=%s has_hyper=%s",
            bool(bitget_data),
            bool(hyper_data),
        )

        if not all([bitget_data, hyper_data]):
            logger.debug("calculate_spreads(): missing market data")
            return {}

        if not isinstance(bitget_data, dict) or not isinstance(hyper_data, dict):
            logger.debug(
                "calculate_spreads(): invalid input types bitget=%s hyper=%s",
                type(bitget_data),
                type(hyper_data),
            )
            return {}

        # Проверяем наличие необходимых полей
        if 'bid' not in bitget_data or 'ask' not in bitget_data:
            logger.debug("calculate_spreads(): bitget missing bid/ask keys=%s", list(bitget_data.keys()))
            return {}

        if 'bid' not in hyper_data or 'ask' not in hyper_data:
            logger.debug("calculate_spreads(): hyperliquid missing bid/ask keys=%s", list(hyper_data.keys()))
            return {}

        bg_bid = bitget_data['bid']
        bg_ask = bitget_data['ask']
        hl_bid = hyper_data['bid']
        hl_ask = hyper_data['ask']

        # Проверка на нулевые цены
        if bg_bid == 0 or bg_ask == 0 or hl_bid == 0 or hl_ask == 0:
            logger.debug(
                "calculate_spreads(): zero price(s) bg_bid=%s bg_ask=%s hl_bid=%s hl_ask=%s",
                bg_bid,
                bg_ask,
                hl_bid,
                hl_ask,
            )
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

        result = {
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

        logger.debug(
            "calculate_spreads() result: B_TO_H=%+.6f%% H_TO_B=%+.6f%%",
            gross_spread_bh,
            gross_spread_hb,
        )

        return result
    
    def calculate_exit_spread_for_market(self, bitget_data: Dict, hyper_data: Dict,
                                        bitget_slippage: Dict = None, hyper_slippage: Dict = None) -> Dict:
        """Расчет выходных спредов для рынка (даже без позиций) - ВАЛОВЫЙ СПРЕД БЕЗ КОМИССИЙ"""

        logger.debug(
            "calculate_exit_spread_for_market() called: has_bitget=%s has_hyper=%s",
            bool(bitget_data),
            bool(hyper_data),
        )

        if not bitget_data or not hyper_data:
            logger.debug("calculate_exit_spread_for_market(): missing market data")
            return {}

        if not isinstance(bitget_data, dict) or not isinstance(hyper_data, dict):
            logger.debug(
                "calculate_exit_spread_for_market(): invalid input types bitget=%s hyper=%s",
                type(bitget_data),
                type(hyper_data),
            )
            return {}

        # Проверяем наличие необходимых полей
        if 'bid' not in bitget_data or 'ask' not in bitget_data:
            logger.debug(
                "calculate_exit_spread_for_market(): bitget missing bid/ask keys=%s",
                list(bitget_data.keys()),
            )
            return {}

        if 'bid' not in hyper_data or 'ask' not in hyper_data:
            logger.debug(
                "calculate_exit_spread_for_market(): hyperliquid missing bid/ask keys=%s",
                list(hyper_data.keys()),
            )
            return {}

        bg_bid = bitget_data['bid']
        bg_ask = bitget_data['ask']
        hl_bid = hyper_data['bid']
        hl_ask = hyper_data['ask']

        if bg_bid == 0 or bg_ask == 0 or hl_bid == 0 or hl_ask == 0:
            logger.debug(
                "calculate_exit_spread_for_market(): zero price(s) bg_bid=%s bg_ask=%s hl_bid=%s hl_ask=%s",
                bg_bid,
                bg_ask,
                hl_bid,
                hl_ask,
            )
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
        
        result = {
            TradeDirection.B_TO_H: exit_spread_bh,
            TradeDirection.H_TO_B: exit_spread_hb
        }

        logger.debug(
            "calculate_exit_spread_for_market() result: B_TO_H=%+.6f%% H_TO_B=%+.6f%%",
            exit_spread_bh,
            exit_spread_hb,
        )

        return result
    
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
        
        # Проверка минимального интервала между ордерами
        min_interval = self.config.get('MIN_ORDER_INTERVAL', 5.0)
        time_since_last = time.time() - self.last_order_time
        if time_since_last < min_interval:
            logger.debug(f"⏳ Order interval: {time_since_last:.1f}s < {min_interval}s, waiting...")
            return None
        
        # Рассчитываем спреды с учетом реального проскальзывания (БЕЗ КОМИССИЙ)
        spreads = self.calculate_spreads(bitget_data, hyper_data, bitget_slippage, hyper_slippage)
        
        if not spreads:
            logger.debug("❌ No spreads calculated - missing market data")
            return None
        
        # MIN_SPREAD_ENTER теперь относится к валовому спреду (без комиссий)
        min_spread_required = self.config['MIN_SPREAD_ENTER'] * 100
        
        # Получаем текущий размер позиции
        current_contracts = self.get_total_position_contracts()
        
        for direction, data in spreads.items():
            # Используем валовый спред без комиссий
            gross_spread = data['gross_spread']
            
            if gross_spread >= min_spread_required:
                # Расчет слиппейджа для проверки
                slippage_used = data.get('slippage_used', {})
                max_slippage = max(
                    slippage_used.get(f"{data['buy_exchange']}_buy", 0),
                    slippage_used.get(f"{data['sell_exchange']}_sell", 0)
                )
                
                risk_ok, reason = self.risk_manager.can_open_position(
                    direction, gross_spread, data['buy_price'],
                    current_position_contracts=current_contracts,
                    slippage=max_slippage
                )
                if risk_ok:
                    logger.info(f"✅ Opportunity FOUND: {direction.value}, spread: {gross_spread:.3f}% - READY TO EXECUTE!")
                    return direction, data
                else:
                    logger.debug(f"Risk check failed for {direction.value}: {reason}")
        
        return None
    
    def _emit_slippage_warning(self, message: str, direction: 'TradeDirection', data: Dict):
        """Эмитирует предупреждение о слишком высоком slippage для отображения в UI"""
        warning = {
            'type': 'slippage_warning',
            'message': message,
            'direction': direction.value if hasattr(direction, 'value') else str(direction),
            'spread': data.get('gross_spread', 0),
            'timestamp': time.time()
        }
        # Сохраняем для веб-интерфейса
        if not hasattr(self, 'pending_warnings'):
            self.pending_warnings = []
        self.pending_warnings.append(warning)
        logger.warning(f"⚠️ SLIPPAGE WARNING: {message}")
    
    def get_pending_warnings(self) -> list:
        """Получение и очистка ожидающих предупреждений"""
        warnings = getattr(self, 'pending_warnings', [])
        self.pending_warnings = []
        return warnings
    
    async def execute_opportunity(self, opportunity: Tuple[TradeDirection, Dict]) -> bool:
        """Исполнение арбитражной возможности с частичным входом"""
        direction, spread_data = opportunity
        
        # Получаем текущий размер позиции для частичного входа
        current_contracts = self.get_total_position_contracts(direction)
        
        # Расчет размера ордера (частичный вход)
        position_size = self.risk_manager.calculate_position_size(
            spread_data['buy_price'], 
            spread_data['gross_spread'],
            current_position_contracts=current_contracts
        )
        
        if position_size['contracts'] <= 0:
            logger.warning(f"Cannot add to position: {position_size.get('reason', 'No capacity')}")
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
        self.last_order_time = time.time()
        
        logger.info(f"✅ Position opened: {position.id}, "
                   f"Direction: {direction.value}, "
                   f"Gross spread: {spread_data['gross_spread']:.3f}%, "
                   f"Slippage: {spread_data['slippage_used']}")
        
        # Сохраняем позиции после открытия
        self._save_positions()
        
        return True
    
    async def monitor_positions(self, bitget_data: Dict, hyper_data: Dict,
                              bitget_slippage: Dict = None, hyper_slippage: Dict = None):
        """Асинхронный мониторинг и закрытие позиций по условиям (только валовый спред)"""
        current_time = time.time()
        
        # Создаем копию списка для безопасной итерации
        positions_to_check = self.open_positions.copy()
        should_save = False
        
        for position in positions_to_check:
            # Проверяем, что позиция все еще открыта
            if position.status != 'open' or position not in self.open_positions:
                continue
            
            # Время удержания (только для мониторинга/логов)
            hold_time = current_time - position.entry_time
            
            # Расчет текущего спреда для выхода (ВАЛОВЫЙ БЕЗ КОМИССИЙ)
            current_spread = self.calculate_exit_spread(position, bitget_data, hyper_data,
                                                       bitget_slippage, hyper_slippage)
            
            # Обновляем состояние позиции
            position.update_exit_spread(current_spread)
            
            # Логируем детальное состояние
            if position.update_count % 10 == 0:  # Каждые 10 обновлений
                logger.debug(f"Position {position.id}: exit_spread={current_spread:.3f}%, "
                            f"target={position.exit_target:.3f}%, hold_time={hold_time:.1f}s")
                should_save = True  # Сохраняем каждые 10 обновлений
            
            # Закрытие по целевому спреду (выходной валовый спред >= целевого)
            # exit_target отрицательный (например -0.05%), но для выхода нужен спред >= этого значения
            if position.should_close():
                logger.info(f"🚀 Closing position {position.id}: "
                           f"Exit spread {current_spread:.3f}% >= target {position.exit_target:.3f}%")
                await self.close_position(position, current_spread, 
                                  f"Exit spread reached: {current_spread:.3f}% >= {position.exit_target:.3f}%")
        
        # Периодически сохраняем позиции (каждые 10 обновлений)
        if should_save and self.open_positions:
            self._save_positions()
    
    async def close_position(self, position: Position, exit_spread: float, reason: str):
        """Асинхронное закрытие позиции"""
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
        exit_result = await self.paper_executor.execute_fok_pair_async(
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
        
        # Сохраняем позиции после закрытия
        self._save_positions()
    
    async def force_close_position(self, position: Position, reason: str):
        """Асинхронное принудительное закрытие позиции"""
        logger.warning(f"⚠️ Force closing position {position.id}: {reason}")
        
        # Рассчитываем текущий спред перед закрытием
        current_spread = position.current_exit_spread
        await self.close_position(position, current_spread, f"FORCE: {reason}")
    
    async def close_all_positions(self, reason: str = "System shutdown"):
        """Асинхронное закрытие всех открытых позиций"""
        for position in self.open_positions[:]:
            await self.force_close_position(position, reason)
    
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
    
    def get_total_position_contracts(self, direction: 'TradeDirection' = None) -> float:
        """Получение общего размера открытых позиций в контрактах
        
        Args:
            direction: если указано, считаем только позиции в этом направлении
            
        Returns:
            Суммарный размер в контрактах
        """
        total = 0.0
        for pos in self.get_open_positions():
            if direction is None or pos.direction == direction:
                total += pos.contracts
        return total
    
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
    
    def get_spread_history(self, limit: int = 100) -> Dict:
        """Получение истории спредов для графика"""
        # Получаем best_spreads_session из bot
        best_spreads_session = {}
        if self.bot and hasattr(self.bot, 'best_spreads_session'):
            best_spreads_session = self.bot.best_spreads_session
        elif hasattr(self, 'best_spreads_session'):
            # Fallback: если атрибут определён напрямую
            best_spreads_session = self.best_spreads_session
        
        # Безопасное получение истории
        entry_spreads = best_spreads_session.get('entry_spreads_history', []) if isinstance(best_spreads_session, dict) else []
        exit_spreads = best_spreads_session.get('exit_spreads_history', []) if isinstance(best_spreads_session, dict) else []
        
        # Берем последние N записей
        recent_entries = entry_spreads[-limit:] if len(entry_spreads) > limit else entry_spreads
        recent_exits = exit_spreads[-limit:] if len(exit_spreads) > limit else exit_spreads
        
        # Строим данные для графика
        labels = []
        entry_bh = []
        entry_hb = []
        exit_bh = []
        exit_hb = []
        timestamps = []
        
        for entry in recent_entries:
            labels.append(entry.get('time_str', datetime.fromtimestamp(entry.get('time', 0)).strftime('%H:%M:%S')) if 'time_str' in entry else datetime.fromtimestamp(entry.get('time', 0)).strftime('%H:%M:%S'))
            direction = entry.get('direction', '')
            spread = entry.get('spread', 0)
            if direction == 'B→H' or direction == 'B_TO_H':
                entry_bh.append(spread)
                entry_hb.append(None)
            elif direction == 'H→B' or direction == 'H_TO_B':
                entry_hb.append(spread)
                entry_bh.append(None)
            else:
                entry_bh.append(None)
                entry_hb.append(None)
            timestamps.append(entry.get('time', 0))
        
        for exit_rec in recent_exits:
            direction = exit_rec.get('direction', '')
            spread = exit_rec.get('spread', 0)
            if direction == 'B→H' or direction == 'B_TO_H':
                exit_bh.append(spread)
                exit_hb.append(None)
            elif direction == 'H→B' or direction == 'H_TO_B':
                exit_hb.append(spread)
                exit_bh.append(None)
            else:
                exit_bh.append(None)
                exit_hb.append(None)
        
        # Заполняем None значения для выравнивания массивов
        max_len = max(len(entry_bh), len(entry_hb), len(exit_bh), len(exit_hb))
        while len(entry_bh) < max_len: entry_bh.append(None)
        while len(entry_hb) < max_len: entry_hb.append(None)
        while len(exit_bh) < max_len: exit_bh.append(None)
        while len(exit_hb) < max_len: exit_hb.append(None)
        while len(labels) < max_len: labels.append(None)
        
        return {
            'labels': [l for l in labels if l is not None],
            'datasets': {
                'entry_bh': [v for v in entry_bh if v is not None],
                'entry_hb': [v for v in entry_hb if v is not None],
                'exit_bh': [v for v in exit_bh if v is not None],
                'exit_hb': [v for v in exit_hb if v is not None],
            },
            'timestamps': [t for t in timestamps if t > 0],
            'health': {
                'bitget': [True] * len([t for t in timestamps if t > 0]),
                'hyper': [True] * len([t for t in timestamps if t > 0]),
            }
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
            
            # 1. Спред давно не обновлялся
            if time.time() - pos.last_spread_update > 60:  # Более минута
                issues.append(f"Spread not updated for {time.time() - pos.last_spread_update:.0f}s")
            
            # 2. Позиция должна закрыться, но не закрывается
            if pos.should_close():
                issues.append(f"Should close (exit_spread={pos.current_exit_spread:.3f}% >= target={pos.exit_target:.3f}%)")
            
            # 3. Мало обновлений спреда
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
    
    def reload_config(self):
        """Перечитывание конфига из модуля"""
        try:
            import importlib
            import config
            importlib.reload(config)
            self.config = config.TRADING_CONFIG
            logger.info("Config reloaded successfully")
            return True
        except Exception as e:
            logger.error(f"Error reloading config: {e}")
            return False

    def update_exit_targets_from_config(self):
        """Обновление целевых выходных спредов для всех открытых позиций на основе текущего конфига"""
        if not self.open_positions:
            return
        
        new_exit_target = self.config['MIN_SPREAD_EXIT'] * 100
        updated_count = 0
        
        for position in self.open_positions:
            if position.status == 'open' and position.exit_target != new_exit_target:
                old_target = position.exit_target
                position.exit_target = new_exit_target
                updated_count += 1
                logger.info(f"Updated position {position.id}: exit_target {old_target:.3f}% -> {new_exit_target:.3f}%")
        
        if updated_count > 0:
            logger.info(f"✅ Updated exit targets for {updated_count} open position(s) to {new_exit_target:.3f}%")
            self._save_positions()
        else:
            logger.debug("No open positions to update")

    async def initialize(self):
        """Инициализация движка"""
        logger.info("Arbitrage Engine initializing...")
        
        # Загружаем сохраненные позиции
        self._load_positions()
        
        # Обновляем целевые спреды из конфига
        self.update_exit_targets_from_config()
        
        logger.info("Arbitrage Engine initialized")
        return True