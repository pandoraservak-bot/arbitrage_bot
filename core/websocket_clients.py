# core/websocket_clients.py
import websocket
import json
import threading
import time
import logging
import asyncio
from typing import Optional, Callable, Dict, List, Tuple
import math

logger = logging.getLogger(__name__)

class OrderBookAnalyzer:
    """Анализатор стакана для расчета проскальзывания"""
    
    @staticmethod
    def calculate_slippage(orderbook: Dict, side: str, amount: float) -> float:
        """
        Расчет проскальзывания для заданного объема и стороны
        
        Args:
            orderbook: Стакан {'bids': [[price, volume], ...], 'asks': [[price, volume], ...]}
            side: 'buy' или 'sell'
            amount: Объем в контрактах
        
        Returns:
            Проскальзывание в процентах (0.01 = 1%)
        """
        if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
            return 0.001  # Возвращаем 0.1% по умолчанию при отсутствии данных
        
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if side == 'buy':
            # При покупке: сколько выше цены мы заплатим за объем
            if not asks:
                return 0.001
            
            best_ask = asks[0][0]
            avg_price = OrderBookAnalyzer.calculate_average_price(asks, amount)
            
            if avg_price > 0 and best_ask > 0:
                slippage = (avg_price / best_ask - 1)
                return max(0.0, slippage)  # Проскальзывание не может быть отрицательным
            return 0.001
            
        else:  # sell
            # При продаже: сколько ниже цены мы получим за объем
            if not bids:
                return 0.001
            
            best_bid = bids[0][0]
            avg_price = OrderBookAnalyzer.calculate_average_price(bids, amount, reverse=True)
            
            if avg_price > 0 and best_bid > 0:
                slippage = (1 - avg_price / best_bid)
                return max(0.0, slippage)  # Проскальзывание не может быть отрицательным
            return 0.001
    
    @staticmethod
    def calculate_average_price(levels: List[List[float]], amount: float, reverse: bool = False) -> float:
        """
        Расчет средней цены для заданного объема
        
        Args:
            levels: Уровни стакана [[цена, объем], ...]
            amount: Требуемый объем
            reverse: Для бидов нужно идти от большей цены к меньшей
        """
        if not levels or amount <= 0:
            return 0.0
        
        remaining_amount = amount
        total_cost = 0.0
        
        if reverse:
            # Для бидов сортируем по убыванию цены
            sorted_levels = sorted(levels, key=lambda x: x[0], reverse=True)
        else:
            # Для асков сортируем по возрастанию цены
            sorted_levels = sorted(levels, key=lambda x: x[0])
        
        for price, volume in sorted_levels:
            if remaining_amount <= 0:
                break
            
            volume_to_take = min(volume, remaining_amount)
            total_cost += price * volume_to_take
            remaining_amount -= volume_to_take
        
        # Если в стакане недостаточно объема, используем последнюю цену для остатка
        if remaining_amount > 0 and sorted_levels:
            last_price = sorted_levels[-1][0]
            total_cost += last_price * remaining_amount
        
        return total_cost / amount if amount > 0 else 0.0
    
    @staticmethod
    def estimate_market_depth(orderbook: Dict, price_move_percent: float = 0.1) -> Dict:
        """
        Оценка глубины рынка: какой объем можно купить/продать без превышения цены
        
        Args:
            orderbook: Стакан
            price_move_percent: На сколько процентов можем двигать цену
        
        Returns:
            Dict с максимальными объемами для покупки и продажи
        """
        result = {
            'buy_volume': 0.0,
            'sell_volume': 0.0,
            'buy_slippage_0_1': 0.0,
            'sell_slippage_0_1': 0.0,
        }
        
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        # Для покупки (asks)
        if asks:
            best_ask = asks[0][0]
            max_price = best_ask * (1 + price_move_percent / 100)
            
            volume = 0.0
            for price, vol in asks:
                if price <= max_price:
                    volume += vol
                else:
                    break
            result['buy_volume'] = volume
            
            # Объем для проскальзывания 0.1%
            volume_0_1 = 0.0
            max_price_0_1 = best_ask * (1 + 0.1 / 100)
            for price, vol in asks:
                if price <= max_price_0_1:
                    volume_0_1 += vol
                else:
                    break
            result['buy_slippage_0_1'] = volume_0_1
        
        # Для продажи (bids)
        if bids:
            best_bid = bids[0][0]
            min_price = best_bid * (1 - price_move_percent / 100)
            
            # Сортируем биды по убыванию цены
            sorted_bids = sorted(bids, key=lambda x: x[0], reverse=True)
            
            volume = 0.0
            for price, vol in sorted_bids:
                if price >= min_price:
                    volume += vol
                else:
                    break
            result['sell_volume'] = volume
            
            # Объем для проскальзывания 0.1%
            volume_0_1 = 0.0
            min_price_0_1 = best_bid * (1 - 0.1 / 100)
            for price, vol in sorted_bids:
                if price >= min_price_0_1:
                    volume_0_1 += vol
                else:
                    break
            result['sell_slippage_0_1'] = volume_0_1
        
        return result

class BaseWebSocketClient:
    """Базовый WebSocket клиент с переподключением"""
    
    def __init__(self, ws_url: str, name: str = "WebSocket"):
        self.ws_url = ws_url
        self.name = name
        self.ws = None
        self.connected = False
        self.reconnecting = False
        self.stop_flag = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 1  # начальная задержка в секундах
        self.last_message_time = 0
        self.heartbeat_interval = 30  # интервал heartbeat в секундах
        self.lock = threading.Lock()
        self.on_disconnect_callback = None
        
    def start(self):
        """Запуск WebSocket соединения с переподключением"""
        self.stop_flag = False
        self.connected = False
        self.reconnecting = False
        
        wst = threading.Thread(target=self._run_forever, daemon=True)
        wst.start()
        
        # Ждем подключения с таймаутом
        timeout = 10
        start_time = time.time()
        while not self.connected and time.time() - start_time < timeout:
            time.sleep(0.1)
        
        return self.connected
    
    def _run_forever(self):
        """Бесконечный цикл соединения с переподключением"""
        while not self.stop_flag:
            try:
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                
                self.ws.run_forever(
                    ping_interval=20,
                    ping_timeout=10
                )
                
            except Exception as e:
                logger.error(f"{self.name} ошибка соединения: {e}")
            
            # Если не остановлен, пытаемся переподключиться
            if not self.stop_flag:
                self._reconnect()
    
    def _reconnect(self):
        """Логика переподключения"""
        if self.reconnecting or self.stop_flag:
            return
        
        self.reconnecting = True
        self.reconnect_attempts += 1
        
        if self.reconnect_attempts > self.max_reconnect_attempts:
            logger.error(f"{self.name} превышено максимальное количество попыток переподключения")
            self.stop_flag = True
            return
        
        delay = min(self.reconnect_delay * (1.5 ** self.reconnect_attempts), 30)
        logger.warning(f"{self.name} переподключение через {delay:.1f}с (попытка {self.reconnect_attempts})")
        
        time.sleep(delay)
        
        # Сбрасываем состояние перед переподключением
        with self.lock:
            self.connected = False
        
        self.reconnecting = False
    
    def _on_open(self, ws):
        """Обработчик открытия соединения"""
        with self.lock:
            self.connected = True
            self.reconnect_attempts = 0
            self.last_message_time = time.time()
        
        logger.info(f"✅ {self.name} подключен")
    
    def _on_message(self, ws, message):
        """Обработчик входящих сообщений"""
        with self.lock:
            self.last_message_time = time.time()
    
    def _on_error(self, ws, error):
        logger.error(f"{self.name} ошибка: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        with self.lock:
            self.connected = False
        
        logger.info(f"{self.name} закрыт: {close_status_code} - {close_msg}")
        
        # Вызываем callback при отключении
        if self.on_disconnect_callback:
            self.on_disconnect_callback()
    
    def is_healthy(self) -> bool:
        """Проверка здоровья соединения"""
        if not self.connected:
            return False
        
        # Проверяем время последнего сообщения
        with self.lock:
            time_since_last_msg = time.time() - self.last_message_time
        
        return time_since_last_msg < self.heartbeat_interval * 2
    
    def disconnect(self):
        """Отключение"""
        self.stop_flag = True
        if self.ws:
            self.ws.close()
        
        with self.lock:
            self.connected = False
    
    def set_disconnect_callback(self, callback: Callable):
        """Установка callback при отключении"""
        self.on_disconnect_callback = callback

class BitgetWebSocketClient(BaseWebSocketClient):
    """WebSocket клиент для Bitget с расчетом проскальзывания"""
    
    def __init__(self, symbol="NVDAUSDT", inst_type="USDT-FUTURES"):
        super().__init__(
            ws_url="wss://ws.bitget.com/v2/ws/public",
            name=f"Bitget({symbol})"
        )
        self.symbol = symbol
        self.inst_type = inst_type
        self.latest_ticker = None
        self.latest_orderbook = None
        self.message_count = 0
        self.position_size = 0.02  # Размер нашей позиции для расчета проскальзывания
    
    def _on_open(self, ws):
        """Обработчик открытия соединения"""
        super()._on_open(ws)
        
        # Подписка на тикер и стакан
        subscriptions = [
            {
                "op": "subscribe",
                "args": [{
                    "instType": self.inst_type,
                    "channel": "ticker",
                    "instId": self.symbol
                }]
            },
            {
                "op": "subscribe",
                "args": [{
                    "instType": self.inst_type,
                    "channel": "books5",
                    "instId": self.symbol
                }]
            }
        ]
        
        for sub in subscriptions:
            if self.ws:
                self.ws.send(json.dumps(sub))
                time.sleep(0.2)
    
    def _on_message(self, ws, message):
        """Обработчик входящих сообщений"""
        super()._on_message(ws, message)
        self.message_count += 1
        
        try:
            data = json.loads(message)
            
            # Обработка подпики
            if data.get('event') == 'subscribe':
                logger.debug(f"Bitget подпика подтверждена: {data.get('arg')}")
                return
            
            # Обработка данных
            if 'data' in data:
                msg_data = data['data']
                if isinstance(msg_data, list) and msg_data:
                    msg_data = msg_data[0]
                
                # Тикер
                if 'bidPr' in msg_data and 'askPr' in msg_data:
                    with self.lock:
                        self.latest_ticker = {
                            'bid': float(msg_data['bidPr']),
                            'ask': float(msg_data['askPr']),
                            'last': float(msg_data.get('lastPr', 0)),
                            'timestamp': msg_data.get('ts', int(time.time() * 1000)),
                        }
                
                # Стакан
                elif 'asks' in msg_data and 'bids' in msg_data:
                    with self.lock:
                        bids = [[float(bid[0]), float(bid[1])] for bid in msg_data['bids'][:10]]  # Берем 10 уровней
                        asks = [[float(ask[0]), float(ask[1])] for ask in msg_data['asks'][:10]]  # Берем 10 уровней
                        
                        bids.sort(key=lambda x: x[0], reverse=True)
                        asks.sort(key=lambda x: x[0])
                        
                        self.latest_orderbook = {
                            'bids': bids,
                            'asks': asks,
                            'timestamp': msg_data.get('ts', int(time.time() * 1000))
                        }
                        
                        # Рассчитываем проскальзывание для нашей позиции
                        if len(bids) > 0 and len(asks) > 0:
                            buy_slippage = OrderBookAnalyzer.calculate_slippage(
                                self.latest_orderbook, 'buy', self.position_size
                            )
                            sell_slippage = OrderBookAnalyzer.calculate_slippage(
                                self.latest_orderbook, 'sell', self.position_size
                            )
                            
                            # Сохраняем расчеты
                            self.latest_orderbook['estimated_slippage'] = {
                                'buy': buy_slippage,
                                'sell': sell_slippage,
                                'position_size': self.position_size,
                                'calculation_time': time.time()
                            }
                        
        except Exception as e:
            logger.error(f"Bitget ошибка обработки сообщения: {e}")
    
    def get_latest_data(self):
        """Получение последних данных"""
        with self.lock:
            if not self.latest_ticker:
                return None
            
            # Используем стакан если есть
            bid = self.latest_ticker['bid']
            ask = self.latest_ticker['ask']
            
            if self.latest_orderbook and self.latest_orderbook['bids'] and self.latest_orderbook['asks']:
                bid = self.latest_orderbook['bids'][0][0]
                ask = self.latest_orderbook['asks'][0][0]
            
            return {
                'bid': bid,
                'ask': ask,
                'last': self.latest_ticker['last'],
                'bids': self.latest_orderbook['bids'] if self.latest_orderbook else [[bid, 0]],
                'asks': self.latest_orderbook['asks'] if self.latest_orderbook else [[ask, 0]],
                'timestamp': self.latest_ticker['timestamp'],
                'symbol': f"{self.symbol}_FUTURES",
                'exchange': 'Bitget',
            }
    
    def get_estimated_slippage(self) -> Dict[str, float]:
        """Получение расчетного проскальзывания"""
        with self.lock:
            if not self.latest_orderbook or 'estimated_slippage' not in self.latest_orderbook:
                return {'buy': 0.001, 'sell': 0.001}  # 0.1% по умолчанию
            
            return {
                'buy': self.latest_orderbook['estimated_slippage']['buy'],
                'sell': self.latest_orderbook['estimated_slippage']['sell']
            }
    
    def get_market_depth(self) -> Dict:
        """Получение оценки глубины рынка"""
        with self.lock:
            if not self.latest_orderbook:
                return {}
            
            return OrderBookAnalyzer.estimate_market_depth(self.latest_orderbook)

class HyperliquidWebSocketClient(BaseWebSocketClient):
    """WebSocket клиент для Hyperliquid с расчетом проскальзывания"""
    
    def __init__(self, symbol="xyz:NVDA"):
        super().__init__(
            ws_url="wss://api.hyperliquid.xyz/ws",
            name=f"Hyperliquid({symbol})"
        )
        self.symbol = symbol
        self.latest_data = None
        self.latest_orderbook = None
        self.message_count = 0
        self.position_size = 0.02  # Размер нашей позиции для расчета проскальзывания
    
    def _on_open(self, ws):
        """Обработчик открытия соединения"""
        super()._on_open(ws)
        
        # Подписка на стакан
        subscribe_msg = {
            "method": "subscribe",
            "subscription": {
                "type": "l2Book",
                "coin": self.symbol
            }
        }
        
        if self.ws:
            self.ws.send(json.dumps(subscribe_msg))
    
    def _on_message(self, ws, message):
        """Обработчик входящих сообщений"""
        super()._on_message(ws, message)
        self.message_count += 1
        
        try:
            data = json.loads(message)
            
            if data.get('channel') == 'l2Book' and data.get('data', {}).get('coin') == self.symbol:
                with self.lock:
                    self.latest_data = data['data']
                    
                    # Преобразуем в формат стакана
                    levels = self.latest_data.get('levels', [[], []])
                    
                    # Парсим биды и аски
                    bids = []
                    for bid in levels[0]:
                        bids.append([float(bid['px']), float(bid['sz'])])
                    
                    asks = []
                    for ask in levels[1]:
                        asks.append([float(ask['px']), float(ask['sz'])])
                    
                    # Сортируем
                    bids.sort(key=lambda x: x[0], reverse=True)
                    asks.sort(key=lambda x: x[0])
                    
                    self.latest_orderbook = {
                        'bids': bids[:10],  # Берем 10 уровней
                        'asks': asks[:10],  # Берем 10 уровней
                        'timestamp': self.latest_data.get('time', int(time.time() * 1000))
                    }
                    
                    # Рассчитываем проскальзывание для нашей позиции
                    if len(bids) > 0 and len(asks) > 0:
                        buy_slippage = OrderBookAnalyzer.calculate_slippage(
                            self.latest_orderbook, 'buy', self.position_size
                        )
                        sell_slippage = OrderBookAnalyzer.calculate_slippage(
                            self.latest_orderbook, 'sell', self.position_size
                        )
                        
                        # Сохраняем расчеты
                        self.latest_orderbook['estimated_slippage'] = {
                            'buy': buy_slippage,
                            'sell': sell_slippage,
                            'position_size': self.position_size,
                            'calculation_time': time.time()
                        }
                    
        except Exception as e:
            logger.error(f"Hyperliquid ошибка обработки сообщения: {e}")
    
    def get_latest_data(self):
        """Получение последних данных"""
        with self.lock:
            if not self.latest_data:
                return None
            
            levels = self.latest_data.get('levels', [[], []])
            
            # Парсим биды и аски
            bids = []
            for bid in levels[0]:
                bids.append([float(bid['px']), float(bid['sz'])])
            
            asks = []
            for ask in levels[1]:
                asks.append([float(ask['px']), float(ask['sz'])])
            
            # Сортируем
            bids.sort(key=lambda x: x[0], reverse=True)
            asks.sort(key=lambda x: x[0])
            
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            
            return {
                'bid': best_bid,
                'ask': best_ask,
                'last': (best_bid + best_ask) / 2 if best_bid and best_ask else 0,
                'bids': bids[:5],
                'asks': asks[:5],
                'timestamp': self.latest_data.get('time', int(time.time() * 1000)),
                'symbol': self.symbol,
                'exchange': 'Hyperliquid',
            }
    
    def get_estimated_slippage(self) -> Dict[str, float]:
        """Получение расчетного проскальзывание"""
        with self.lock:
            if not self.latest_orderbook or 'estimated_slippage' not in self.latest_orderbook:
                return {'buy': 0.001, 'sell': 0.001}  # 0.1% по умолчанию
            
            return {
                'buy': self.latest_orderbook['estimated_slippage']['buy'],
                'sell': self.latest_orderbook['estimated_slippage']['sell']
            }
    
    def get_market_depth(self) -> Dict:
        """Получение оценки глубины рынка"""
        with self.lock:
            if not self.latest_orderbook:
                return {}
            
            return OrderBookAnalyzer.estimate_market_depth(self.latest_orderbook)