# REST клиент для Hyperliquid (если WebSocket не работает)
import requests
import time
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class HyperliquidRESTClient:
    """REST клиент для получения данных с Hyperliquid"""
    
    def __init__(self):
        self.base_url = "https://api.hyperliquid.xyz"
        self.symbol = "NVDA"
        self.last_update = 0
        self.latest_data = {}
        
    def get_orderbook(self) -> Optional[Dict]:
        """Получение стакана ордеров"""
        try:
            url = f"{self.base_url}/info"
            payload = {
                "type": "l2Book",
                "coin": self.symbol
            }
            
            response = requests.post(url, json=payload, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                
                if isinstance(data, dict) and 'levels' in data:
                    levels = data['levels']
                    
                    # Находим лучшие цены
                    best_bid = None
                    best_ask = None
                    
                    for level in levels:
                        if level.get('side') == 'B':  # Bid
                            price = float(level.get('px', 0))
                            if best_bid is None or price > best_bid:
                                best_bid = price
                        elif level.get('side') == 'A':  # Ask
                            price = float(level.get('px', 0))
                            if best_ask is None or price < best_ask:
                                best_ask = price
                    
                    if best_bid and best_ask and best_bid > 0 and best_ask > 0:
                        self.latest_data = {
                            'exchange': 'hyperliquid',
                            'symbol': f"xyz:{self.symbol}",
                            'coin': self.symbol,
                            'bid': best_bid,
                            'ask': best_ask,
                            'mid': (best_bid + best_ask) / 2,
                            'spread': (best_ask - best_bid) / best_bid * 100,
                            'timestamp': time.time(),
                            'data_type': 'rest_orderbook'
                        }
                        self.last_update = time.time()
                        return self.latest_data
            
            logger.warning(f"Hyperliquid REST ошибка: {response.status_code}")
            
        except Exception as e:
            logger.error(f"Ошибка получения данных Hyperliquid: {e}")
        
        return None
    
    def get_latest_data(self) -> Dict:
        """Получение последних данных"""
        # Если данные устарели (больше 2 секунд), обновляем
        if time.time() - self.last_update > 2:
            self.get_orderbook()
        
        return self.latest_data.copy()
    
    def start(self) -> bool:
        """Запуск клиента"""
        logger.info("Hyperliquid REST клиент запущен")
        return True
    
    def disconnect(self):
        """Отключение клиента"""
        logger.info("Hyperliquid REST клиент отключен")