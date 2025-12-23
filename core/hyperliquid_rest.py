# REST клиент для Hyperliquid
import requests
import time
import logging
import threading
from typing import Dict, Optional
import json

logger = logging.getLogger(__name__)

class HyperliquidRESTClient:
    """REST клиент для получения данных с Hyperliquid"""
    
    def __init__(self):
        self.base_url = "https://api.hyperliquid.xyz"
        self.symbol = "NVDA"
        self.connected = True  # Всегда считаем, что REST доступен
        self.running = False
        
        # Данные
        self.latest_data = {
            'exchange': 'hyperliquid',
            'symbol': 'xyz:NVDA',
            'bid': 171.0,
            'ask': 172.0,
            'mid': 171.5,
            'spread': 0.584,
            'timestamp': time.time(),
            'data_type': 'rest'
        }
        self.last_update = 0
        self.update_thread = None
        
        # Статистика
        self.update_count = 0
        self.error_count = 0
    
    def fetch_orderbook(self) -> Optional[Dict]:
        """Получение стакана ордеров с Hyperliquid"""
        try:
            url = f"{self.base_url}/info"
            payload = {
                "type": "l2Book",
                "coin": self.symbol
            }
            
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
            
            response = requests.post(
                url, 
                json=payload, 
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if isinstance(data, dict):
                    levels = data.get("levels", [])
                    
                    if levels and len(levels) == 2:
                        # Первый массив - биды (покупка), второй - аски (продажа)
                        bids = levels[0]  # Уже отсортированы по убыванию цены
                        asks = levels[1]  # Уже отсортированы по возрастанию цены
                        
                        if bids and asks:
                            # Лучший бид - самый высокий (первый в массиве)
                            best_bid_entry = bids[0]
                            best_bid = float(best_bid_entry.get("px", 0))
                            
                            # Лучший аск - самый низкий (первый в массиве)
                            best_ask_entry = asks[0]
                            best_ask = float(best_ask_entry.get("px", 0))
                            
                            if best_bid > 0 and best_ask > 0 and best_ask > best_bid:
                                return {
                                    'exchange': 'hyperliquid',
                                    'symbol': f'xyz:{self.symbol}',
                                    'bid': best_bid,
                                    'ask': best_ask,
                                    'bid_size': float(best_bid_entry.get("sz", 0)),
                                    'ask_size': float(best_ask_entry.get("sz", 0)),
                                    'mid': (best_bid + best_ask) / 2,
                                    'spread': (best_ask - best_bid) / best_bid * 100,
                                    'timestamp': time.time(),
                                    'data_type': 'orderbook',
                                    'update_count': self.update_count
                                }
            
            logger.warning(f"Hyperliquid REST: неверный ответ, статус {response.status_code}")
            
        except requests.exceptions.Timeout:
            logger.warning("Hyperliquid REST: timeout")
            self.error_count += 1
        except requests.exceptions.ConnectionError:
            logger.warning("Hyperliquid REST: connection error")
            self.error_count += 1
        except Exception as e:
            logger.error(f"Hyperliquid REST ошибка: {e}")
            self.error_count += 1
        
        return None
    
    def update_loop(self):
        """Цикл обновления данных"""
        while self.running:
            try:
                # Получаем данные
                new_data = self.fetch_orderbook()
                
                if new_data:
                    self.latest_data = new_data
                    self.last_update = time.time()
                    self.update_count += 1
                    
                    # Логируем каждые 100 обновлений
                    if self.update_count % 500 == 0:  # Увеличили с 100 до 500 - меньше спама
                        logger.info(f"Hyperliquid REST: {self.update_count} обновлений, "
                                   f"цена: {new_data['bid']:.2f}/{new_data['ask']:.2f}")
                else:
                    # Если не удалось получить данные, логируем ошибку
                    if self.error_count % 10 == 0:
                        logger.warning(f"Hyperliquid REST: ошибок {self.error_count}")
                
                # Ждем 500мс перед следующим обновлением
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле обновления Hyperliquid: {e}")
                time.sleep(1)
    
    def start(self) -> bool:
        """Запуск клиента"""
        try:
            logger.info("Запуск Hyperliquid REST клиента...")
            
            # Пробуем получить данные сразу
            initial_data = self.fetch_orderbook()
            if initial_data:
                self.latest_data = initial_data
                self.last_update = time.time()
                logger.info(f"Hyperliquid REST: начальные данные получены - "
                           f"{initial_data['bid']:.2f}/{initial_data['ask']:.2f}")
            else:
                logger.warning("Hyperliquid REST: не удалось получить начальные данные")
            
            # Запускаем поток обновления
            self.running = True
            self.update_thread = threading.Thread(target=self.update_loop, daemon=True)
            self.update_thread.start()
            
            logger.info("✅ Hyperliquid REST клиент запущен")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка запуска Hyperliquid REST клиента: {e}")
            return False
    
    def disconnect(self):
        """Отключение клиента"""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=2)
        logger.info("Hyperliquid REST клиент отключен")
    
    def get_latest_data(self) -> Dict:
        """Получение последних данных"""
        # Если данные устарели более чем на 5 секунд, считаем их неактуальными
        if time.time() - self.last_update > 5:
            self.connected = False
        else:
            self.connected = True
        
        return self.latest_data.copy()
    
    def get_queued_data(self, timeout: float = 0.1) -> Optional[Dict]:
        """Получение данных из очереди (для совместимости)"""
        return None