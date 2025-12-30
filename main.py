# main.py
import asyncio
import time
import logging
import sys
import os
from datetime import datetime
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LOGGING_CONFIG, TRADING_CONFIG, STATS_CONFIG, DISPLAY_CONFIG, TRADING_MODE
from core.websocket_clients import BitgetWebSocketClient, HyperliquidWebSocketClient
from core.risk_manager import RiskManager
from core.paper_executor import PaperTradeExecutor
from core.arbitrage_engine import ArbitrageEngine, TradeDirection
from core.live_executor import LiveTradeExecutor

# Try to import web server (optional)
try:
    from web_server import WebDashboardServer, integrate_web_dashboard
    WEB_DASHBOARD_AVAILABLE = True
except ImportError:
    WEB_DASHBOARD_AVAILABLE = False
    WebDashboardServer = None
    integrate_web_dashboard = None

# Настройка логирования
# FileHandler: все уровни (включая DEBUG) - для записи в файл
# StreamHandler: только INFO и выше - для отображения в консоли
file_handler = logging.FileHandler(LOGGING_CONFIG['LOG_FILE'], encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)

# Форматирование
formatter = logging.Formatter(LOGGING_CONFIG['LOG_FORMAT'])
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.DEBUG,  # Общий уровень - самый низкий, обработчики фильтруют
    handlers=[file_handler, stream_handler]
)
logger = logging.getLogger(__name__)

class TradingMode(Enum):
    """Режимы торговли"""
    ACTIVE = "ACTIVE"
    PARTIAL = "PARTIAL"
    STOPPED = "STOPPED"

class DisplayMode(Enum):
    """Режимы отображения"""
    COMPACT = "compact"
    ULTRA_COMPACT = "ultra_compact"
    DASHBOARD = "dashboard"

class NVDAFuturesArbitrageBot:
    """Главный бот для арбитража фьючерсов NVDA"""
    
    def __init__(self):
        self.config = TRADING_CONFIG
        self.stats_config = STATS_CONFIG
        self.display_config = DISPLAY_CONFIG
        
        # Режим отображения
        self.display_mode = DisplayMode(self.display_config.get('DISPLAY_MODE', 'compact'))
        
        # Инициализация компонентов
        self.risk_manager = RiskManager()
        self.paper_executor = PaperTradeExecutor()
        self.live_executor = None  # Инициализируется позже если режим live
        self.arb_engine = ArbitrageEngine(self.risk_manager, self.paper_executor, self)
        
        # WebSocket клиенты
        self.bitget_ws = None
        self.hyper_ws = None
        
        # Состояние
        self.running = False
        self.trading_enabled = True  # Флаг для паузы торговли через UI
        self.trading_mode = TradingMode.STOPPED
        self.session_start = time.time()
        self.last_mode_change = time.time()
        
        # Флаги состояния WebSocket
        self.bitget_healthy = False
        self.hyper_healthy = False
        
        # Кеш для спредов
        self.current_spread = 0.0
        self.spread_direction = None
        self.spread_calculation_time = 0
        self.current_slippage_info = {}
        
        # Статистика лучших спредов за сессию
        self.best_spreads_session = {
            'best_entry_spread': 0.0,           # Лучший валовый спред для входа
            'best_entry_direction': None,       # Направление лучшего входа
            'best_entry_time': None,            # Время лучшего входа
            
            # Лучшие выходные спреды (рассчитываются всегда, даже без позиций)
            'best_exit_spread_bh': float('inf'),  # Лучший спред для выхода B→H
            'best_exit_spread_hb': float('inf'),  # Лучший спред для выхода H→B
            'best_exit_spread_overall': float('inf'),  # Абсолютно лучший выходной спред
            'best_exit_direction': None,        # Направление лучшего выхода
            'best_exit_time': None,             # Время лучшего выхода
            'best_exit_with_position': False,   # Был ли связан с позицией
            
            'entry_spreads_history': [],        # История всех спредов для входа
            'exit_spreads_history': [],         # История всех спредов для выхода
        }
        
        # Статистика сессии
        self.session_stats = {
            'start_time': datetime.now(),
            'total_checks': 0,
            'total_trades': 0,
            'bitget_updates': 0,
            'hyper_updates': 0,
            'bitget_connections': 0,
            'hyper_connections': 0,
            'bitget_disconnects': 0,
            'hyper_disconnects': 0,
            'mode_changes': 0,
            'time_in_active': 0,
            'time_in_partial': 0,
            'time_in_stopped': 0,
            'max_spread': 0.0,
            'min_spread': float('inf'),
            'avg_spread': 0.0,
            'spread_sum': 0.0,
            'spread_count': 0,
            'last_spread': 0.0,
            'last_spread_direction': None,
            'positive_spreads': 0,
            'negative_spreads': 0,
        }
        
        # Web dashboard server (initialized later)
        self.web_dashboard = None
        
    async def initialize(self):
        """Инициализация всех компонентов"""
        logger.info("=" * 60)
        logger.info("NVDA АРБИТРАЖНЫЙ БОТ")
        logger.info(f"Режим отображения: {self.display_mode.value}")
        logger.info("=" * 60)
        
        try:
            # Инициализация компонентов
            await self.risk_manager.initialize()
            await self.paper_executor.initialize()
            await self.arb_engine.initialize()
            
            # Инициализация live executor если режим live сохранён
            if TRADING_MODE.get('LIVE_ENABLED', False):
                logger.info("🔴 Загружен режим LIVE торговли из файла")
                self.live_executor = LiveTradeExecutor()
                await self.live_executor.initialize()
                status = self.live_executor.get_status()
                logger.info(f"Live executor status: HL={status.get('hyperliquid_connected')}, BG={status.get('bitget_connected')}")
                
                # Синхронизация позиций при запуске
                try:
                    hl_pos = await self.live_executor.get_hyperliquid_position()
                    bg_pos = await self.live_executor.get_bitget_position()
                    hl_size = float(hl_pos.get('s', 0)) if hl_pos else 0
                    bg_size = float(bg_pos.get('total', 0)) if bg_pos else 0
                    real_size = min(abs(hl_size), abs(bg_size))
                    if self.arb_engine.open_positions:
                        for pos in self.arb_engine.open_positions:
                            if pos.mode == 'live' and pos.status == 'open':
                                pos.update_contracts_from_api(real_size)
                        self.arb_engine._save_positions()
                except Exception as e:
                    logger.error(f"Error during startup position sync: {e}")
            else:
                logger.info("📄 Режим Paper торговли")
            
            # Установка callback для обновления статистики лучших спредов выхода
            self.arb_engine.set_exit_spread_callback(self.update_exit_spread_stats)
            
            # Инициализация WebSocket клиентов
            await self.initialize_websockets()
            
            logger.info("✅ Инициализация завершена")
            logger.info(f"Время: {datetime.now().strftime('%H:%M:%S')}")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка инициализации: {e}")
            return False
    
    async def initialize_websockets(self):
        """Инициализация WebSocket соединений"""
        logger.info("Подключение WebSocket...")
        
        # Получаем текущий event loop для передачи в WebSocket клиенты
        current_loop = asyncio.get_running_loop()
        
        # Создание и настройка WebSocket клиентов
        self.bitget_ws = BitgetWebSocketClient(event_loop=current_loop)
        self.hyper_ws = HyperliquidWebSocketClient(event_loop=current_loop)
        
        # Установка callback для отслеживания отключений
        self.bitget_ws.set_disconnect_callback(self.on_bitget_disconnect)
        self.hyper_ws.set_disconnect_callback(self.on_hyper_disconnect)
        
        # Запуск соединений
        logger.info("Bitget WebSocket...")
        bitget_ok = self.bitget_ws.start()
        
        await asyncio.sleep(2)
        
        logger.info("Hyperliquid WebSocket...")
        hyper_ok = self.hyper_ws.start()
        
        # Обновление состояния
        await self.update_trading_mode()
        
        return self.trading_mode != TradingMode.STOPPED
    
    def on_bitget_disconnect(self):
        """Обработчик отключения Bitget"""
        self.session_stats['bitget_disconnects'] += 1
        logger.warning("Bitget отключен")
        asyncio.create_task(self.update_trading_mode())
    
    def on_hyper_disconnect(self):
        """Обработчик отключения Hyperliquid"""
        self.session_stats['hyper_disconnects'] += 1
        logger.warning("Hyperliquid отключен")
        asyncio.create_task(self.update_trading_mode())
    
    async def update_trading_mode(self):
        """Обновление режима торговли"""
        bitget_healthy = self.bitget_ws.is_healthy() if self.bitget_ws else False
        hyper_healthy = self.hyper_ws.is_healthy() if self.hyper_ws else False
        
        self.bitget_healthy = bitget_healthy
        self.hyper_healthy = hyper_healthy
        
        if bitget_healthy and hyper_healthy:
            new_mode = TradingMode.ACTIVE
        elif bitget_healthy or hyper_healthy:
            new_mode = TradingMode.PARTIAL
        else:
            new_mode = TradingMode.STOPPED
        
        # Обновляем статистику времени в режимах
        await self.update_mode_time_stats()
        
        if new_mode != self.trading_mode:
            old_mode = self.trading_mode
            self.trading_mode = new_mode
            self.last_mode_change = time.time()
            self.session_stats['mode_changes'] += 1
            
            mode_changes = {
                (TradingMode.ACTIVE, TradingMode.PARTIAL): "→ Частичная",
                (TradingMode.ACTIVE, TradingMode.STOPPED): "→ Остановлена",
                (TradingMode.PARTIAL, TradingMode.ACTIVE): "→ Активна",
                (TradingMode.PARTIAL, TradingMode.STOPPED): "→ Остановлена",
                (TradingMode.STOPPED, TradingMode.ACTIVE): "→ Активна",
                (TradingMode.STOPPED, TradingMode.PARTIAL): "→ Частичная",
            }
            
            change_desc = mode_changes.get((old_mode, new_mode), "Изменен")
            logger.info(f"Режим: {change_desc}")
    
    async def update_mode_time_stats(self):
        """Обновление статистики времени в режимах"""
        current_time = time.time()
        time_in_mode = current_time - self.last_mode_change
        
        if self.trading_mode == TradingMode.ACTIVE:
            self.session_stats['time_in_active'] += time_in_mode
        elif self.trading_mode == TradingMode.PARTIAL:
            self.session_stats['time_in_partial'] += time_in_mode
        elif self.trading_mode == TradingMode.STOPPED:
            self.session_stats['time_in_stopped'] += time_in_mode
        
        self.last_mode_change = current_time
    
    def calculate_current_spread(self) -> tuple:
        """Расчет текущего спреда с учетом проскальзывания"""
        if not self.bitget_ws or not self.hyper_ws:
            return 0.0, None, "Нет подключения"
        
        bitget_data = self.bitget_ws.get_latest_data()
        hyper_data = self.hyper_ws.get_latest_data()
        
        if not bitget_data or not hyper_data:
            return 0.0, None, "Нет данных"
        
        if 'bid' not in bitget_data or 'ask' not in bitget_data:
            return 0.0, None, "Нет данных Bitget"
        
        if 'bid' not in hyper_data or 'ask' not in hyper_data:
            return 0.0, None, "Нет данных Hyperliquid"
        
        bitget_slippage = self.bitget_ws.get_estimated_slippage()
        hyper_slippage = self.hyper_ws.get_estimated_slippage()
        
        try:
            spreads = self.arb_engine.calculate_spreads(
                bitget_data, hyper_data, bitget_slippage, hyper_slippage
            )
            
            if not spreads:
                return 0.0, None, "Не удалось рассчитать"
            
            best_spread = -float('inf')
            best_direction = None
            best_data = None
            
            for direction, spread_data in spreads.items():
                gross_spread = spread_data.get('gross_spread', -float('inf'))
                if gross_spread > best_spread:
                    best_spread = gross_spread
                    best_direction = direction
                    best_data = spread_data
            
            # Обновляем кеш
            self.current_spread = best_spread
            self.spread_direction = best_direction
            self.spread_calculation_time = time.time()
            
            if best_data:
                self.current_slippage_info = best_data.get('slippage_used', {})
            
            # Обновляем статистику спредов для входа
            if best_spread != -float('inf'):
                self.update_entry_spread_stats(best_spread, best_direction)
            
            # ОБНОВЛЕННО: Рассчитываем и обновляем выходные спреды (даже без позиций)
            if self.bitget_healthy and self.hyper_healthy:
                self.calculate_and_update_exit_spreads(bitget_data, hyper_data, bitget_slippage, hyper_slippage)
            
            # Обновляем статистику
            self.session_stats['last_spread'] = best_spread
            self.session_stats['last_spread_direction'] = best_direction.value if best_direction else None
            
            # Считаем статистику спредов только при активном режиме
            if self.trading_mode == TradingMode.ACTIVE and best_spread != -float('inf'):
                self.update_spread_stats(best_spread)
            
            return best_spread, best_direction, "OK"
            
        except Exception as e:
            return 0.0, None, f"Ошибка: {str(e)[:30]}"
    
    def calculate_and_update_exit_spreads(self, bitget_data, hyper_data, bitget_slippage, hyper_slippage):
        """Расчет и обновление выходных спредов (даже без позиций)"""
        if not bitget_data or not hyper_data:
            return
        
        try:
            # Рассчитываем выходные спреды для обоих направлений
            exit_spreads = self.arb_engine.calculate_exit_spread_for_market(
                bitget_data, hyper_data, bitget_slippage, hyper_slippage
            )
            
            if exit_spreads:
                # Обновляем лучшие спреды для каждого направления
                for direction, exit_spread in exit_spreads.items():
                    self.update_exit_spread_stats(exit_spread, direction, None, False)
                
                # Обновляем абсолютно лучший выходной спред
                best_exit_overall = min(exit_spreads.values())
                best_exit_dir = min(exit_spreads, key=exit_spreads.get)
                
                if best_exit_overall < self.best_spreads_session['best_exit_spread_overall']:
                    self.best_spreads_session['best_exit_spread_overall'] = best_exit_overall
                    self.best_spreads_session['best_exit_direction'] = best_exit_dir.value if best_exit_dir else None
                    self.best_spreads_session['best_exit_time'] = time.time()
                    self.best_spreads_session['best_exit_with_position'] = False
                    
                    # Логируем только если спред значительно улучшился (более 10%)
                    if self.best_spreads_session['best_exit_spread_overall'] != float('inf'):
                        improvement = ((self.best_spreads_session['best_exit_spread_overall'] - best_exit_overall) /
                                     abs(self.best_spreads_session['best_exit_spread_overall']) * 100)
                        if abs(improvement) > 10:
                            logger.info(f"🎯 Новый рекордный выходной спред (без позиции): {best_exit_overall:.3f}% ({best_exit_dir.value if best_exit_dir else 'N/A'})")
                    else:
                        logger.info(f"🎯 Новый рекордный выходной спред (без позиции): {best_exit_overall:.3f}% ({best_exit_dir.value if best_exit_dir else 'N/A'})")
                    
        except Exception as e:
            logger.debug(f"Ошибка расчета выходных спредов: {e}")
    
    def update_entry_spread_stats(self, spread: float, direction):
        """Обновление статистики спредов для входа"""
        # Добавляем в историю
        self.best_spreads_session['entry_spreads_history'].append({
            'spread': spread,
            'direction': direction.value if direction else None,
            'time': time.time()
        })
        
        # Ограничиваем размер истории
        max_history = 1000
        if len(self.best_spreads_session['entry_spreads_history']) > max_history:
            self.best_spreads_session['entry_spreads_history'] = self.best_spreads_session['entry_spreads_history'][-max_history:]
        
        # Обновляем лучший спред для входа
        if spread > self.best_spreads_session['best_entry_spread']:
            self.best_spreads_session['best_entry_spread'] = spread
            self.best_spreads_session['best_entry_direction'] = direction.value if direction else None
            self.best_spreads_session['best_entry_time'] = time.time()
            
            # Логируем только если спред значительно улучшился (более 10%)
            if self.best_spreads_session['best_entry_spread'] > 0:
                improvement = ((spread - self.best_spreads_session['best_entry_spread']) /
                             self.best_spreads_session['best_entry_spread'] * 100)
                if abs(improvement) > 10:
                    logger.info(f"🎯 Новый рекордный спред для входа: {spread:.3f}% ({direction.value if direction else 'N/A'})")
            else:
                logger.info(f"🎯 Новый рекордный спред для входа: {spread:.3f}% ({direction.value if direction else 'N/A'})")
    
    def update_exit_spread_stats(self, spread: float, direction=None, position_id: str = None, from_position: bool = True):
        """Обновление статистики спредов для выхода"""
        # Добавляем в историю
        self.best_spreads_session['exit_spreads_history'].append({
            'spread': spread,
            'direction': direction.value if direction else None,
            'position_id': position_id,
            'from_position': from_position,
            'time': time.time()
        })
        
        # Ограничиваем размер истории
        max_history = 1000
        if len(self.best_spreads_session['exit_spreads_history']) > max_history:
            self.best_spreads_session['exit_spreads_history'] = self.best_spreads_session['exit_spreads_history'][-max_history:]
        
        # Обновляем лучшие спреды для конкретного направления
        if direction == TradeDirection.B_TO_H:
            if spread < self.best_spreads_session['best_exit_spread_bh']:
                self.best_spreads_session['best_exit_spread_bh'] = spread
                # Убрали spam - логируем только значительные улучшения
        elif direction == TradeDirection.H_TO_B:
            if spread < self.best_spreads_session['best_exit_spread_hb']:
                self.best_spreads_session['best_exit_spread_hb'] = spread
                # Убрали spam - логируем только значительные улучшения
        
        # Обновляем абсолютно лучший выходной спред
        if spread < self.best_spreads_session['best_exit_spread_overall']:
            self.best_spreads_session['best_exit_spread_overall'] = spread
            self.best_spreads_session['best_exit_direction'] = direction.value if direction else None
            self.best_spreads_session['best_exit_time'] = time.time()
            self.best_spreads_session['best_exit_with_position'] = from_position
            
            # Логируем только значительные улучшения (более 10%)
            should_log = False
            if self.best_spreads_session['best_exit_spread_overall'] != float('inf'):
                improvement = ((self.best_spreads_session['best_exit_spread_overall'] - spread) /
                             abs(self.best_spreads_session['best_exit_spread_overall']) * 100)
                should_log = abs(improvement) > 10
            
            if should_log or self.best_spreads_session['best_exit_spread_overall'] == float('inf'):
                if from_position and position_id:
                    logger.info(f"🎯 Новый рекордный спред для выхода: {spread:.3f}% (позиция {position_id})")
                else:
                    logger.info(f"🎯 Новый рекордный выходной спред (рыночный): {spread:.3f}% ({direction.value if direction else 'N/A'})")
    
    def update_spread_stats(self, spread: float):
        """Обновление статистики спредов"""
        if spread == -float('inf'):
            return
        
        self.session_stats['spread_sum'] += spread
        self.session_stats['spread_count'] += 1
        
        if spread > self.session_stats['max_spread']:
            self.session_stats['max_spread'] = spread
        
        if spread < self.session_stats['min_spread']:
            self.session_stats['min_spread'] = spread
        
        if self.session_stats['spread_count'] > 0:
            self.session_stats['avg_spread'] = (
                self.session_stats['spread_sum'] / self.session_stats['spread_count']
            )
        
        if spread > 0:
            self.session_stats['positive_spreads'] += 1
        elif spread < 0:
            self.session_stats['negative_spreads'] += 1
    
    async def trading_cycle(self):
        """Основной торговый цикл"""
        logger.info("Начало торгового цикла...")
        
        try:
            last_status_update = time.time()
            last_health_check = time.time()
            last_spread_calculation = 0
            last_diagnosis = 0
            last_exit_spread_calculation = 0
            
            while self.running:
                try:
                    current_time = time.time()
                    
                    # Диагностика каждые 30 секунд
                    if current_time - last_diagnosis >= 30:
                        if self.arb_engine.has_open_positions():
                            self.arb_engine.log_diagnosis()
                        last_diagnosis = current_time
                    
                    # Проверка здоровья каждые 3 секунды
                    if current_time - last_health_check >= 3:
                        await self.update_trading_mode()
                        last_health_check = current_time
                    
                    self.session_stats['total_checks'] += 1
                    
                    # Получение данных
                    bitget_data = None
                    hyper_data = None
                    
                    if self.bitget_ws and self.bitget_healthy:
                        bitget_data = self.bitget_ws.get_latest_data()
                        if bitget_data and 'timestamp' in bitget_data:
                            self.session_stats['bitget_updates'] += 1
                    
                    if self.hyper_ws and self.hyper_healthy:
                        hyper_data = self.hyper_ws.get_latest_data()
                        if hyper_data and 'timestamp' in hyper_data:
                            self.session_stats['hyper_updates'] += 1
                    
                    # В зависимости от режима торговли
                    if self.trading_mode == TradingMode.ACTIVE:
                        bitget_slippage = self.bitget_ws.get_estimated_slippage() if self.bitget_ws else None
                        hyper_slippage = self.hyper_ws.get_estimated_slippage() if self.hyper_ws else None
                        
                        await self.active_trading_mode(bitget_data, hyper_data, bitget_slippage, hyper_slippage)
                        
                    elif self.trading_mode == TradingMode.PARTIAL:
                        await self.partial_trading_mode(bitget_data, hyper_data)
                        
                    elif self.trading_mode == TradingMode.STOPPED:
                        await self.stopped_trading_mode()
                    
                    # Расчет входных спредов каждую секунду
                    if current_time - last_spread_calculation >= 1:
                        if (self.bitget_ws and self.hyper_ws and 
                            self.bitget_healthy and self.hyper_healthy):
                            self.calculate_current_spread()
                            last_spread_calculation = current_time
                    
                    # Расчет выходных спредов каждые 0.5 секунды (чаще, так как они важнее для мониторинга)
                    if current_time - last_exit_spread_calculation >= 0.5:
                        if (self.bitget_ws and self.hyper_ws and 
                            self.bitget_healthy and self.hyper_healthy and
                            bitget_data and hyper_data):
                            
                            bitget_slippage = self.bitget_ws.get_estimated_slippage() if self.bitget_ws else None
                            hyper_slippage = self.hyper_ws.get_estimated_slippage() if self.hyper_ws else None
                            
                            self.calculate_and_update_exit_spreads(bitget_data, hyper_data, bitget_slippage, hyper_slippage)
                            last_exit_spread_calculation = current_time
                    
                    # Обновление дисплея каждые 2 секунды
                    if current_time - last_status_update >= 2:
                        self.display_status()
                        last_status_update = current_time
                    
                    # Периодическая синхронизация позиций с реальными данными (раз в минуту)
                    if int(current_time) % 60 == 0:
                        try:
                            # Получаем позиции с обеих бирж
                            hl_pos = await self.live_executor.get_hyperliquid_position() if self.live_executor else None
                            bg_pos = await self.live_executor.get_bitget_position() if self.live_executor else None
                            
                            hl_size = float(hl_pos.get('s', 0)) if hl_pos else 0
                            bg_size = float(bg_pos.get('total', 0)) if bg_pos else 0
                            
                            # Размер арбитражной позиции - это минимум из двух сторон (абсолютное значение)
                            real_size = min(abs(hl_size), abs(bg_size))
                            
                            if self.arb_engine.open_positions:
                                # Для NVDA у нас обычно одна позиция, обновляем ее
                                for pos in self.arb_engine.open_positions:
                                    if pos.mode == 'live' and pos.status == 'open':
                                        pos.update_contracts_from_api(real_size)
                                
                                # Сохраняем обновленные данные
                                self.arb_engine._save_positions()
                        except Exception as e:
                            logger.error(f"Error during position sync: {e}")

                    await asyncio.sleep(self.config['MAIN_LOOP_INTERVAL'])
                    
                except Exception as e:
                    logger.error(f"Ошибка в итерации цикла: {e}")
                    import traceback
                    traceback.print_exc()
                    await asyncio.sleep(1)  # Пауза перед следующей попыткой
                    
        except Exception as e:
            logger.error(f"Критическая ошибка торгового цикла: {e}")
            import traceback
            traceback.print_exc()
    
    async def active_trading_mode(self, bitget_data, hyper_data, bitget_slippage, hyper_slippage):
        """Активный режим торговли"""
        has_bitget_data = bitget_data and 'bid' in bitget_data and 'ask' in bitget_data
        has_hyper_data = hyper_data and 'bid' in hyper_data and 'ask' in hyper_data
        
        if has_bitget_data and has_hyper_data:
            # Всегда мониторим позиции, если они есть
            if self.arb_engine.has_open_positions():
                # Мониторинг позиций работает даже в режиме паузы
                await self.arb_engine.monitor_positions(bitget_data, hyper_data, bitget_slippage, hyper_slippage)
            elif not self.trading_enabled:
                # Пауза - не открываем новые позиции
                pass
            else:
                # Нет позиций - ищем возможности для входа
                opportunity = self.arb_engine.find_opportunity(
                    bitget_data, hyper_data, bitget_slippage, hyper_slippage
                )
                
                if opportunity:
                    logger.info(f"Найдена возможность: {opportunity[0].value}")
                    success = await self.arb_engine.execute_opportunity(opportunity)
                    if success:
                        self.session_stats['total_trades'] += 1
    
    async def partial_trading_mode(self, bitget_data, hyper_data):
        """Частичный режим"""
        has_bitget_data = bitget_data and 'bid' in bitget_data and 'ask' in bitget_data
        has_hyper_data = hyper_data and 'bid' in hyper_data and 'ask' in hyper_data
        
        # В частичном режиме только логируем состояние позиций
        if self.arb_engine.has_open_positions():
            current_time = time.time()
            
            for position in self.arb_engine.get_open_positions():
                hold_time = current_time - position.entry_time
                if hold_time % 30 < 1:  # Логируем каждые 30 секунд
                    logger.info(f"Позиция {position.id} в частичном режиме: "
                              f"возраст {hold_time:.1f}с, "
                              f"данные Bitget: {'есть' if has_bitget_data else 'нет'}, "
                              f"данные Hyper: {'есть' if has_hyper_data else 'нет'}")
    
    async def stopped_trading_mode(self):
        """Остановленный режим"""
        if self.arb_engine.has_open_positions():
            current_time = time.time()
            
            for position in self.arb_engine.get_open_positions():
                hold_time = current_time - position.entry_time
                if hold_time % 30 < 1:  # Логируем каждые 30 секунд
                    logger.warning(f"Позиция {position.id} в остановленном режиме: "
                                 f"возраст {hold_time:.1f}с, "
                                 f"ожидание восстановления соединения")
    
    def display_status(self):
        """Основной метод отображения статуса - выбирает нужный режим"""
        if self.display_mode == DisplayMode.COMPACT:
            self.display_status_compact()
        elif self.display_mode == DisplayMode.ULTRA_COMPACT:
            self.display_status_ultra_compact()
        elif self.display_mode == DisplayMode.DASHBOARD:
            self.display_status_dashboard()
        else:
            self.display_status_compact()  # По умолчанию
    
    def display_status_compact(self):
        """КОМПАКТНЫЙ РЕЖИМ - показываем ВАЛОВЫЕ спреды"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
        
        runtime = time.time() - self.session_start
        hours, remainder = divmod(runtime, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # ===== ЗАГОЛОВОК =====
        print(f"┌{'─'*58}┐")
        print(f"│ NVDA АРБИТРАЖНЫЙ БОТ │ {datetime.now().strftime('%H:%M:%S')} │")
        print(f"│ ВСЕ СПРЕДЫ - ВАЛОВЫЕ (без комиссий){' '*19}│")
        print(f"├{'─'*58}┤")
        
        # ===== СТАТУС И СОЕДИНЕНИЯ =====
        if self.trading_mode == TradingMode.ACTIVE:
            mode_str = "🟢 АКТИВЕН"
        elif self.trading_mode == TradingMode.PARTIAL:
            mode_str = "🟡 ЧАСТИЧНЫЙ"
        else:
            mode_str = "🔴 ОСТАНОВЛЕН"
        
        bitget_status = "🟢" if self.bitget_healthy else "🔴"
        hyper_status = "🟢" if self.hyper_healthy else "🔴"
        
        print(f"│ Статус: {mode_str:<12} Соединения: Bitget:{bitget_status} Hyper:{hyper_status} │")
        print(f"├{'─'*58}┤")
        
        # ===== ЦЕНЫ =====
        bitget_data = self.bitget_ws.get_latest_data() if self.bitget_ws else None
        hyper_data = self.hyper_ws.get_latest_data() if self.hyper_ws else None
        
        if bitget_data and 'bid' in bitget_data:
            bg_bid = bitget_data.get('bid', 0)
            bg_ask = bitget_data.get('ask', 0)
            print(f"│ Bitget:     ${bg_bid:7.2f} / ${bg_ask:7.2f} ", end="")
        else:
            print(f"│ Bitget:     Нет данных{' '*26}", end="")
        
        if hyper_data and 'bid' in hyper_data:
            hl_bid = hyper_data.get('bid', 0)
            hl_ask = hyper_data.get('ask', 0)
            print(f"│ Hyper: ${hl_bid:7.2f} / ${hl_ask:7.2f} │")
        else:
            print(f"│ Hyper: Нет данных{' '*13}│")
        
        print(f"├{'─'*58}┤")
        
        # ===== ПРОСКАЛЬЗЫВАНИЕ =====
        bitget_slippage = self.bitget_ws.get_estimated_slippage() if self.bitget_ws else None
        hyper_slippage = self.hyper_ws.get_estimated_slippage() if self.hyper_ws else None

        if self.display_config.get('SHOW_SLIPPAGE_DETAILS', True):
            if bitget_slippage:
                bg_buy = bitget_slippage['buy'] * 100
                bg_sell = bitget_slippage['sell'] * 100
                print(f"│ Проскальзывание Bitget:  купить:{bg_buy:5.3f}% продать:{bg_sell:5.3f}% │")
            else:
                print(f"│ Проскальзывание Bitget:  нет данных{' '*25}│")

            if hyper_slippage:
                hl_buy = hyper_slippage['buy'] * 100
                hl_sell = hyper_slippage['sell'] * 100
                print(f"│ Проскальзывание Hyper:   купить:{hl_buy:5.3f}% продать:{hl_sell:5.3f}% │")
            else:
                print(f"│ Проскальзывание Hyper:   нет данных{' '*25}│")

            print(f"├{'─'*58}┤")
        
        # ===== ТЕКУЩИЕ ВАЛОВЫЕ СПРЕДЫ ДЛЯ ВХОДА =====
        if self.bitget_ws and self.hyper_ws and self.bitget_healthy and self.hyper_healthy:
            bitget_data = self.bitget_ws.get_latest_data()
            hyper_data = self.hyper_ws.get_latest_data()
            
            if bitget_data and hyper_data:
                spreads = self.arb_engine.calculate_spreads(bitget_data, hyper_data, 
                                                           bitget_slippage, hyper_slippage)
                
                if spreads:
                    bh_gross = spreads[TradeDirection.B_TO_H]['gross_spread']
                    hb_gross = spreads[TradeDirection.H_TO_B]['gross_spread']
                    
                    # Определяем лучший спред для входа
                    best_entry = max(bh_gross, hb_gross)
                    best_dir = TradeDirection.B_TO_H if bh_gross >= hb_gross else TradeDirection.H_TO_B
                    
                    # Цвет для входа (чем выше, тем лучше)
                    if best_entry >= 0.3:
                        entry_color = "🟢"
                    elif best_entry >= 0.22:  # MIN_SPREAD_ENTER = 0.22%
                        entry_color = "🟡"
                    elif best_entry > 0:
                        entry_color = "🔵"
                    else:
                        entry_color = "🔴"
                    
                    print(f"│ Входные спреды (валовые): B→H:{bh_gross:6.3f}% H→B:{hb_gross:6.3f}% │")
                    print(f"│ Лучший вход: {entry_color} {best_entry:6.3f}% ({best_dir.value})", end="")
                    
                    # Целевой спред для входа
                    min_enter = self.config['MIN_SPREAD_ENTER'] * 100
                    print(f" │ Цель: ≥{min_enter:.3f}% │")
                else:
                    print(f"│ Входные спреды: не удалось рассчитать{' '*22}│")
            else:
                print(f"│ Входные спреды: нет данных{' '*32}│")
        else:
            print(f"│ Входные спреды: нет соединения{' '*29}│")
        
        print(f"├{'─'*58}┤")
        
        # ===== ЛУЧШИЕ СПРЕДЫ ЗА СЕССИЮ =====
        best_entry = self.best_spreads_session['best_entry_spread']
        best_exit_overall = self.best_spreads_session['best_exit_spread_overall']
        best_exit_bh = self.best_spreads_session['best_exit_spread_bh']
        best_exit_hb = self.best_spreads_session['best_exit_spread_hb']
        
        if best_entry > 0:
            entry_time_str = ""
            if self.best_spreads_session['best_entry_time']:
                entry_ago = time.time() - self.best_spreads_session['best_entry_time']
                if entry_ago < 60:
                    entry_time_str = f"({int(entry_ago)}с назад)"
                elif entry_ago < 3600:
                    entry_time_str = f"({int(entry_ago/60)}м назад)"
                else:
                    entry_time_str = f"({int(entry_ago/3600)}ч назад)"
            
            entry_dir = self.best_spreads_session['best_entry_direction'] or ""
            print(f"│ Лучший вход за сессию: {entry_dir} {best_entry:6.3f}% {entry_time_str:<10}│")
        else:
            print(f"│ Лучший вход за сессию: ---{' '*32}│")
        
        # ОБНОВЛЕНО: Показываем лучшие выходные спреды (всегда, даже без позиций)
        if best_exit_overall != float('inf'):
            exit_time_str = ""
            if self.best_spreads_session['best_exit_time']:
                exit_ago = time.time() - self.best_spreads_session['best_exit_time']
                if exit_ago < 60:
                    exit_time_str = f"({int(exit_ago)}с назад)"
                elif exit_ago < 3600:
                    exit_time_str = f"({int(exit_ago/60)}м назад)"
                else:
                    exit_time_str = f"({int(exit_ago/3600)}ч назад)"
            
            exit_dir = self.best_spreads_session['best_exit_direction'] or ""
            exit_type = "поз" if self.best_spreads_session['best_exit_with_position'] else "рын"
            
            print(f"│ Лучший выход за сессию: {exit_dir} {best_exit_overall:6.3f}% [{exit_type}] {exit_time_str:<6}│")
            
            # Дополнительно показываем спреды по направлениям
            if best_exit_bh != float('inf') and best_exit_hb != float('inf'):
                print(f"│   B→H: {best_exit_bh:6.3f}%   H→B: {best_exit_hb:6.3f}%{' '*23}│")
        else:
            print(f"│ Лучший выход за сессию: ---{' '*31}│")
        
        print(f"├{'─'*58}┤")
        
        # ===== ВЫХОДНЫЕ СПРЕДЫ (открытые позиции) =====
        open_positions = self.arb_engine.get_open_positions()
        max_positions_shown = self.display_config.get('MAX_POSITIONS_SHOWN', 3)
        
        if open_positions:
            print(f"│ Выходные спреды (валовые) для позиций:{' '*19}│")
            
            for pos in open_positions[:max_positions_shown]:
                exit_spread = pos.current_exit_spread
                age = pos.get_age_formatted()
                
                # Цвет для выхода (чем ниже/отрицательнее, тем лучше)
                if exit_spread <= -0.1:  # Очень хороший отрицательный спред
                    exit_color = "🟢"
                elif exit_spread <= 0:  # Отрицательный или нулевой
                    exit_color = "🟡"
                elif exit_spread <= pos.exit_target:  # В пределах цели
                    exit_color = "🟠"
                else:  # Выше цели
                    exit_color = "🔴"
                
                should_close = pos.should_close()
                close_marker = "🚀" if should_close else ""
                
                print(f"│ #{pos.id}: {pos.direction.value} {age} {exit_color} {exit_spread:6.3f}% ", end="")
                print(f"(цель: ≤{pos.exit_target:.3f}%) {close_marker}{' '*6}│")
                
                # Дополнительная информация
                if should_close:
                    print(f"│   ⚡ ГОТОВО К ЗАКРЫТИЮ!{' '*37}│")
        else:
            print(f"│ Нет открытых позиций{' '*39}│")
        
        print(f"├{'─'*58}┤")
        
        # ===== ДЕТАЛИ ПОСЛЕДНЕЙ ПОЗИЦИИ =====
        if open_positions:
            latest_pos = open_positions[-1]
            stats = latest_pos.get_statistics()
            
            print(f"│ Детали #{latest_pos.id}: Возраст: {stats['age_formatted']} ", end="")
            print(f"Обновлений: {stats['spread_updates']:3} │")
            
            if 'recent_spreads' in stats:
                recent = ", ".join([f"{s:.3f}%" for s in stats['recent_spreads']])
                print(f"│ Последние спреды: {recent:<38}│")
        
        print(f"├{'─'*58}┤")
        
        # ===== СТАТИСТИКА СЕССИИ =====
        print(f"│ Время работы: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d} ", end="")
        print(f"Проверок: {self.session_stats['total_checks']:6} │")
        print(f"│ Сделок: {self.session_stats['total_trades']:3} ", end="")
        
        # Статистика по времени в режимах
        if runtime > 0:
            active_pct = (self.session_stats['time_in_active'] / runtime * 100)
            partial_pct = (self.session_stats['time_in_partial'] / runtime * 100)
            stopped_pct = (self.session_stats['time_in_stopped'] / runtime * 100)
            print(f"Режимы: Акт:{active_pct:4.1f}% Час:{partial_pct:4.1f}% Стоп:{stopped_pct:4.1f}% │")
        else:
            print(f"{' '*39}│")
        
        print(f"├{'─'*58}┤")
        
        # ===== ПОРТФЕЛЬ =====
        if self.display_config.get('SHOW_PORTFOLIO_DETAILS', True):
            portfolio = self.paper_executor.get_portfolio()
            usdt = portfolio.get('USDT', 0)
            nvda = portfolio.get('NVDA', 0)
            
            print(f"│ Портфель: USDT:${usdt:8.2f} NVDA:{nvda:9.6f} ", end="")
            
            if bitget_data and 'bid' in bitget_data:
                avg_price = bitget_data.get('bid', 170)
                total_value = usdt + nvda * avg_price
                pnl = total_value - 1000.0
                
                if pnl > 0:
                    pnl_color = "🟢"
                elif pnl < 0:
                    pnl_color = "🔴"
                else:
                    pnl_color = "⚪"
                
                print(f"Итого:${total_value:8.2f} PnL:{pnl_color}${pnl:7.2f} │")
            else:
                print(f"{' '*20}│")
        else:
            print(f"│{' '*56}│")
        
        print(f"└{'─'*58}┘")
        print(f" Ctrl+C для остановки | Режим: {self.display_mode.value}")
    
    def display_status_ultra_compact(self):
        """УЛЬТРАКОМПАКТНЫЙ РЕЖИМ - минимализм"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
        
        runtime = time.time() - self.session_start
        h = int(runtime // 3600)
        m = int((runtime % 3600) // 60)
        s = int(runtime % 60)
        
        # ===== ЗАГОЛОВОК =====
        print(f"┌{'─'*70}┐")
        print(f"│ NVDA АРБИТРАЖ │ {datetime.now().strftime('%H:%M:%S')} │ Работа: {h:02d}:{m:02d}:{s:02d} │")
        print(f"│ Режим: УЛЬТРАКОМПАКТНЫЙ{' '*45}│")
        print(f"├{'─'*70}┤")
        
        # ===== СТАТУС И СОЕДИНЕНИЯ =====
        if self.trading_mode == TradingMode.ACTIVE:
            mode_str = "🟢 АКТ"
        elif self.trading_mode == TradingMode.PARTIAL:
            mode_str = "🟡 ЧАСТ"
        else:
            mode_str = "🔴 СТОП"
        
        bg_status = "🟢" if self.bitget_healthy else "🔴"
        hl_status = "🟢" if self.hyper_healthy else "🔴"
        
        print(f"│ Статус: {mode_str} │ Bitget:{bg_status} Hyper:{hl_status} │ Сделок: {self.session_stats['total_trades']:3} │ Проверок: {self.session_stats['total_checks']:6} │")
        print(f"├{'─'*70}┤")
        
        # ===== ЦЕНЫ =====
        bitget_data = self.bitget_ws.get_latest_data() if self.bitget_ws else None
        hyper_data = self.hyper_ws.get_latest_data() if self.hyper_ws else None
        
        if bitget_data and 'bid' in bitget_data:
            bg_bid = bitget_data.get('bid', 0)
            bg_ask = bitget_data.get('ask', 0)
            bg_str = f"${bg_bid:.2f}/${bg_ask:.2f}"
        else:
            bg_str = "нет данных"
        
        if hyper_data and 'bid' in hyper_data:
            hl_bid = hyper_data.get('bid', 0)
            hl_ask = hyper_data.get('ask', 0)
            hl_str = f"${hl_bid:.2f}/${hl_ask:.2f}"
        else:
            hl_str = "нет данных"
        
        print(f"│ Bitget: {bg_str:>15} │ Hyper: {hl_str:>15} │", end="")
        
        # ===== ВХОДНЫЕ СПРЕДЫ =====
        if self.bitget_ws and self.hyper_ws and self.bitget_healthy and self.hyper_healthy:
            bitget_data = self.bitget_ws.get_latest_data()
            hyper_data = self.hyper_ws.get_latest_data()
            
            if bitget_data and hyper_data:
                spreads = self.arb_engine.calculate_spreads(bitget_data, hyper_data)
                
                if spreads:
                    bh_gross = spreads[TradeDirection.B_TO_H]['gross_spread']
                    hb_gross = spreads[TradeDirection.H_TO_B]['gross_spread']
                    best_entry = max(bh_gross, hb_gross)
                    
                    if best_entry >= 0.22:
                        spread_color = "🟢"
                    elif best_entry > 0:
                        spread_color = "🟡"
                    else:
                        spread_color = "🔴"
                    
                    print(f" Вход: {spread_color} {best_entry:5.3f}% │")
                else:
                    print(f" Вход: --- │")
            else:
                print(f" Вход: --- │")
        else:
            print(f" Вход: --- │")
        
        print(f"├{'─'*70}┤")
        
        # ===== ЛУЧШИЕ СПРЕДЫ ЗА СЕССИЮ =====
        best_entry = self.best_spreads_session['best_entry_spread']
        best_exit_overall = self.best_spreads_session['best_exit_spread_overall']
        
        if best_entry > 0:
            entry_str = f"{best_entry:5.3f}%"
        else:
            entry_str = "---"
        
        if best_exit_overall != float('inf'):
            exit_str = f"{best_exit_overall:5.3f}%"
            exit_type = "поз" if self.best_spreads_session['best_exit_with_position'] else "рын"
            exit_str = f"{exit_str}[{exit_type}]"
        else:
            exit_str = "---"
        
        print(f"│ Рекорды: Вход: {entry_str} | Выход: {exit_str}{' '*25}│")
        print(f"├{'─'*70}┤")
        
        # ===== ВЫХОДНЫЕ СПРЕДЫ (позиции) =====
        positions = self.arb_engine.get_open_positions()
        if positions:
            print(f"│ Позиций: {len(positions):2} ", end="")
            
            # Показываем спред последней позиции
            last_pos = positions[-1]
            exit_spread = last_pos.current_exit_spread
            
            if exit_spread <= last_pos.exit_target:
                exit_color = "🟢"
            elif exit_spread <= 0:
                exit_color = "🟡"
            else:
                exit_color = "🔴"
            
            print(f"│ Последняя: {last_pos.direction.value} {exit_color} {exit_spread:5.3f}% ", end="")
            print(f"(цель: ≤{last_pos.exit_target:.3f}%) │")
        else:
            print(f"│ Нет позиций{' '*55}│")
        
        print(f"├{'─'*70}┤")
        
        # ===== ТЕКУЩИЕ ВЫХОДНЫЕ СПРЕДЫ (рыночные, без позиций) =====
        # Рассчитываем текущие выходные спреды
        if (self.bitget_ws and self.hyper_ws and self.bitget_healthy and self.hyper_healthy and
            bitget_data and hyper_data):
            
            try:
                bitget_slippage = self.bitget_ws.get_estimated_slippage() if self.bitget_ws else None
                hyper_slippage = self.hyper_ws.get_estimated_slippage() if self.hyper_ws else None
                
                exit_spreads = self.arb_engine.calculate_exit_spread_for_market(
                    bitget_data, hyper_data, bitget_slippage, hyper_slippage
                )
                
                if exit_spreads:
                    current_exit_bh = exit_spreads[TradeDirection.B_TO_H]
                    current_exit_hb = exit_spreads[TradeDirection.H_TO_B]
                    current_best_exit = min(current_exit_bh, current_exit_hb)
                    
                    # Определяем цвет для текущего лучшего выхода
                    if current_best_exit <= -0.1:
                        exit_color = "🟢"
                    elif current_best_exit <= 0:
                        exit_color = "🟡"
                    elif current_best_exit <= self.config['MIN_SPREAD_EXIT'] * 100:
                        exit_color = "🟠"
                    else:
                        exit_color = "🔴"
                    
                    print(f"│ Рыночные выходы: B→H:{current_exit_bh:5.3f}% H→B:{current_exit_hb:5.3f}% │")
                    print(f"│ Лучший рынок: {exit_color} {current_best_exit:5.3f}% (цель: ≤{self.config['MIN_SPREAD_EXIT']*100:.3f}%) │")
            except Exception:
                print(f"│ Рыночные выходы: расчет...{' '*44}│")
        
        print(f"├{'─'*70}┤")
        
        # ===== ПОРТФЕЛЬ =====
        portfolio = self.paper_executor.get_portfolio()
        usdt = portfolio.get('USDT', 0)
        nvda = portfolio.get('NVDA', 0)
        
        if bitget_data and 'bid' in bitget_data:
            price = bitget_data.get('bid', 170)
            total = usdt + nvda * price
            pnl = total - 1000.0
            pnl_color = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
            print(f"│ USDT:${usdt:.2f} NVDA:{nvda:.4f} │ Всего:${total:.2f} PnL:{pnl_color}${pnl:.2f} │")
        else:
            print(f"│ USDT:${usdt:.2f} NVDA:{nvda:.4f} │ Всего:--- │")
        
        print(f"└{'─'*70}┘")
        print(f" Ctrl+C для остановки | Режим: {self.display_mode.value}")
    
    def display_status_dashboard(self):
        """DASHBOARD РЕЖИМ - современный стиль табло"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
        
        runtime = time.time() - self.session_start
        h = int(runtime // 3600)
        m = int((runtime % 3600) // 60)
        s = int(runtime % 60)
        
        # ===== ШАПКА =====
        print(f"╔{'═'*68}╗")
        print(f"║{'NVDA ARBITRAGE BOT':^68}║")
        print(f"║{'Режим: DASHBOARD':^68}║")
        print(f"╠{'═'*68}╣")
        
        # ===== СТРОКА 1: Время и статус =====
        if not self.trading_enabled:
            mode_icon = "⏸️"
            mode_text = "PAUSED"
        elif self.trading_mode == TradingMode.ACTIVE:
            mode_icon = "▶️"
            mode_text = "ACTIVE"
        elif self.trading_mode == TradingMode.PARTIAL:
            mode_icon = "⏸️"
            mode_text = "PARTIAL"
        else:
            mode_icon = "⏹️"
            mode_text = "STOPPED"
        
        bg_icon = "●" if self.bitget_healthy else "○"
        hl_icon = "●" if self.hyper_healthy else "○"
        
        print(f"║ Время: {h:02d}:{m:02d}:{s:02d} │ Статус: {mode_icon} {mode_text:7} │ Bitget:{bg_icon} Hyper:{hl_icon} │ Проверок: {self.session_stats['total_checks']:6} ║")
        print(f"╠{'─'*68}╣")
        
        # ===== СТРОКА 2: Цены и входные спреды =====
        bitget_data = self.bitget_ws.get_latest_data() if self.bitget_ws else None
        hyper_data = self.hyper_ws.get_latest_data() if self.hyper_ws else None
        
        if bitget_data and 'bid' in bitget_data:
            bg_price = (bitget_data['bid'] + bitget_data['ask']) / 2
            bg_str = f"${bg_price:.2f}"
        else:
            bg_str = "---"
        
        if hyper_data and 'bid' in hyper_data:
            hl_price = (hyper_data['bid'] + hyper_data['ask']) / 2
            hl_str = f"${hl_price:.2f}"
        else:
            hl_str = "---"
        
        print(f"║ Цены: Bitget: {bg_str:>8} │ Hyperliquid: {hl_str:>8} │", end="")
        
        # Входные спреды
        if self.bitget_ws and self.hyper_ws and self.bitget_healthy and self.hyper_healthy:
            bitget_data = self.bitget_ws.get_latest_data()
            hyper_data = self.hyper_ws.get_latest_data()
            
            if bitget_data and hyper_data:
                spreads = self.arb_engine.calculate_spreads(bitget_data, hyper_data)
                
                if spreads:
                    best_entry = max(spreads[TradeDirection.B_TO_H]['gross_spread'], 
                                   spreads[TradeDirection.H_TO_B]['gross_spread'])
                    
                    if best_entry >= 0.3:
                        spread_icon = "🟩"
                    elif best_entry >= 0.22:
                        spread_icon = "🟨"
                    elif best_entry > 0:
                        spread_icon = "🟦"
                    else:
                        spread_icon = "🟥"
                    
                    print(f" Вход: {spread_icon} {best_entry:5.3f}% ║")
                else:
                    print(f" Вход: --- ║")
            else:
                print(f" Вход: --- ║")
        else:
            print(f" Вход: --- ║")
        
        print(f"╠{'─'*68}╣")
        
        # ===== СТРОКА 3: Лучшие спреды за сессию =====
        best_entry = self.best_spreads_session['best_entry_spread']
        best_exit_overall = self.best_spreads_session['best_exit_spread_overall']
        
        if best_entry > 0:
            entry_str = f"{best_entry:+.3f}%"
            if self.best_spreads_session['best_entry_direction']:
                entry_str = f"{self.best_spreads_session['best_entry_direction']} {entry_str}"
        else:
            entry_str = "---"
        
        if best_exit_overall != float('inf'):
            exit_str = f"{best_exit_overall:+.3f}%"
            exit_type = "поз" if self.best_spreads_session['best_exit_with_position'] else "рын"
            exit_str = f"{exit_str}[{exit_type}]"
        else:
            exit_str = "---"
        
        print(f"║ Рекорды: Вход: {entry_str:>12} │ Выход: {exit_str:>12} │{' '*16}║")
        print(f"╠{'─'*68}╣")
        
        # ===== СТРОКА 4: Текущие рыночные выходные спреды =====
        # Рассчитываем текущие выходные спреды
        current_exit_info = "---"
        if (self.bitget_ws and self.hyper_ws and self.bitget_healthy and self.hyper_healthy and
            bitget_data and hyper_data):
            
            try:
                bitget_slippage = self.bitget_ws.get_estimated_slippage() if self.bitget_ws else None
                hyper_slippage = self.hyper_ws.get_estimated_slippage() if self.hyper_ws else None
                
                exit_spreads = self.arb_engine.calculate_exit_spread_for_market(
                    bitget_data, hyper_data, bitget_slippage, hyper_slippage
                )
                
                if exit_spreads:
                    current_exit_bh = exit_spreads[TradeDirection.B_TO_H]
                    current_exit_hb = exit_spreads[TradeDirection.H_TO_B]
                    current_best_exit = min(current_exit_bh, current_exit_hb)
                    
                    # Определяем иконку для текущего выхода
                    if current_best_exit <= -0.1:
                        exit_icon = "🟢"
                    elif current_best_exit <= 0:
                        exit_icon = "🟡"
                    elif current_best_exit <= self.config['MIN_SPREAD_EXIT'] * 100:
                        exit_icon = "🟠"
                    else:
                        exit_icon = "🔴"
                    
                    current_exit_info = f"{exit_icon} B→H:{current_exit_bh:+.2f}% H→B:{current_exit_hb:+.2f}%"
            except Exception:
                current_exit_info = "расчет..."
        
        print(f"║ Рынок: {current_exit_info:<40}║")
        print(f"╠{'─'*68}╣")
        
        # ===== СТРОКА 5: Позиции и портфель =====
        positions = self.arb_engine.get_open_positions()
        portfolio = self.paper_executor.get_portfolio()
        usdt = portfolio.get('USDT', 0)
        nvda = portfolio.get('NVDA', 0)
        
        print(f"║ Позиций: {len(positions):2} ", end="")
        
        if bitget_data and 'bid' in bitget_data:
            price = bitget_data.get('bid', 170)
            total = usdt + nvda * price
            pnl = total - 1000.0
            pnl_icon = "📈" if pnl > 0 else "📉" if pnl < 0 else "📊"
            print(f"│ Портфель: ${total:.2f} {pnl_icon} ${pnl:.2f} │", end="")
        else:
            print(f"│ Портфель: ${usdt:.2f} │", end="")
        
        # Выходные спреды позиций
        if positions:
            last_pos = positions[-1]
            exit_spread = last_pos.current_exit_spread
            
            if exit_spread <= last_pos.exit_target:
                exit_icon = "🟢"
            elif exit_spread <= 0:
                exit_icon = "🟡"
            else:
                exit_icon = "🔴"
            
            print(f" Последняя: {exit_icon} {exit_spread:5.3f}% ║")
        else:
            print(f" Активных позиций нет{' '*13}║")
        
        print(f"╚{'═'*68}╝")
        print(f" Нажмите Ctrl+C для остановки | Режим: {self.display_mode.value}")
    
    async def run(self):
        """Запуск бота"""
        logger.info("Запуск NVDA Арбитражного Бота...")
        
        if not await self.initialize():
            logger.error("Не удалось инициализировать бота")
            return
        
        self.running = True
        self.session_start = time.time()
        self.last_mode_change = time.time()
        
        # Initialize web dashboard server
        if WEB_DASHBOARD_AVAILABLE and integrate_web_dashboard:
            try:
                self.web_dashboard = integrate_web_dashboard(self, host='0.0.0.0', port=5000)
                if self.web_dashboard:
                    await self.web_dashboard.start()
                    logger.info("🌐 Web Dashboard: http://0.0.0.0:5000")
            except Exception as e:
                logger.warning(f"Не удалось запустить web dashboard: {e}")
        
        try:
            await self.trading_cycle()
        except KeyboardInterrupt:
            logger.info("\n🛑 Бот остановлен")
        except Exception as e:
            logger.error(f"Ошибка бота: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Корректное завершение работы"""
        logger.info("Завершение работы...")
        self.running = False
        
        # Stop web dashboard server
        if self.web_dashboard:
            try:
                await self.web_dashboard.stop()
            except Exception as e:
                logger.warning(f"Ошибка при остановке web dashboard: {e}")
        
        await self.update_mode_time_stats()
        
        close_on_shutdown = False
        if close_on_shutdown and self.arb_engine.has_open_positions():
            logger.warning("Закрытие позиций...")
            await self.arb_engine.close_all_positions("Завершение работы")
        
        # Сохраняем открытые позиции перед завершением
        if self.arb_engine.has_open_positions():
            logger.info(f"Сохранение {len(self.arb_engine.get_open_positions())} открытых позиций...")
            self.arb_engine._save_positions()
        
        if self.bitget_ws:
            self.bitget_ws.disconnect()
        if self.hyper_ws:
            self.hyper_ws.disconnect()
        
        await self.save_final_stats()
        
        logger.info("✅ Завершено")
    
    async def save_final_stats(self):
        """Сохранение финальной статистики"""
        try:
            engine_stats = self.arb_engine.get_statistics()
            self.session_stats['total_pnl'] = engine_stats.get('total_pnl', 0)
            self.session_stats['total_fees'] = engine_stats.get('total_fees', 0)
            self.session_stats['total_volume'] = engine_stats.get('total_volume', 0)
            
            import json
            stats_file = os.path.join("data", "session_stats.json")
            
            stats_data = {
                **self.session_stats,
                **self.best_spreads_session,
                'end_time': datetime.now().isoformat(),
                'runtime_seconds': time.time() - self.session_start,
                'final_mode': self.trading_mode.value,
                'open_positions_at_end': len(self.arb_engine.get_open_positions()),
                'current_spread_at_end': self.current_spread,
                'spread_direction_at_end': self.spread_direction.value if self.spread_direction else None,
                'slippage_info_at_end': self.current_slippage_info,
                'display_mode_used': self.display_mode.value,
            }
            
            # Преобразуем time.time() значения в строки для JSON
            for key in ['best_entry_time', 'best_exit_time']:
                if stats_data[key] is not None:
                    stats_data[key] = datetime.fromtimestamp(stats_data[key]).isoformat()
            
            os.makedirs("data", exist_ok=True)
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats_data, f, indent=2, default=str)
            
            logger.info(f"Статистика сохранена в {stats_file}")
            
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")

async def main():
    """Точка входа"""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    bot = NVDAFuturesArbitrageBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())