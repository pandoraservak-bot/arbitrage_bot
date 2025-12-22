# core/connection_manager.py
import time
import logging
import asyncio
from typing import Dict, Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    CONNECTED = "CONNECTED"
    CONNECTING = "CONNECTING"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"

class WebSocketManager:
    """Менеджер для управления WebSocket соединениями"""
    
    def __init__(self):
        self.connections = {}
        self.state_callbacks = {}
        self.reconnect_tasks = {}
        
    def register_connection(self, name: str, ws_client, health_check_func: Callable):
        """Регистрация WebSocket соединения"""
        self.connections[name] = {
            'client': ws_client,
            'health_check': health_check_func,
            'state': ConnectionState.DISCONNECTED,
            'last_healthy': 0,
            'disconnect_time': 0,
            'reconnect_attempts': 0,
        }
        
        # Устанавливаем callback для отключений
        if hasattr(ws_client, 'set_disconnect_callback'):
            ws_client.set_disconnect_callback(
                lambda: self.on_connection_disconnected(name)
            )
    
    def on_connection_disconnected(self, name: str):
        """Обработчик отключения соединения"""
        if name in self.connections:
            self.connections[name]['state'] = ConnectionState.DISCONNECTED
            self.connections[name]['disconnect_time'] = time.time()
            
            logger.warning(f"Соединение {name} отключено")
            
            # Запускаем задачу переподключения
            asyncio.create_task(self.reconnect_connection(name))
            
            # Вызываем callback
            if name in self.state_callbacks:
                self.state_callbacks[name](ConnectionState.DISCONNECTED)
    
    async def reconnect_connection(self, name: str):
        """Переподключение соединения"""
        if name not in self.connections:
            return
        
        conn = self.connections[name]
        
        # Если уже переподключается, выходим
        if conn['state'] == ConnectionState.CONNECTING:
            return
        
        conn['state'] = ConnectionState.CONNECTING
        conn['reconnect_attempts'] += 1
        
        max_attempts = 10
        base_delay = 1
        
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Попытка переподключения {name} ({attempt}/{max_attempts})")
                
                # Останавливаем старый клиент
                conn['client'].disconnect()
                await asyncio.sleep(1)
                
                # Запускаем новый
                success = conn['client'].start()
                
                if success:
                    conn['state'] = ConnectionState.CONNECTED
                    conn['reconnect_attempts'] = 0
                    conn['last_healthy'] = time.time()
                    
                    logger.info(f"✅ {name} успешно переподключен")
                    
                    # Вызываем callback
                    if name in self.state_callbacks:
                        self.state_callbacks[name](ConnectionState.CONNECTED)
                    
                    return
                
            except Exception as e:
                logger.error(f"Ошибка при переподключении {name}: {e}")
            
            # Экспоненциальная задержка
            delay = base_delay * (2 ** min(attempt, 5))
            logger.info(f"Следующая попытка через {delay} секунд")
            await asyncio.sleep(delay)
        
        # Если не удалось переподключиться
        conn['state'] = ConnectionState.ERROR
        logger.error(f"❌ Не удалось переподключить {name} после {max_attempts} попыток")
    
    def check_connection_health(self, name: str) -> bool:
        """Проверка здоровья соединения"""
        if name not in self.connections:
            return False
        
        conn = self.connections[name]
        
        try:
            is_healthy = conn['health_check']()
            
            if is_healthy:
                conn['last_healthy'] = time.time()
                if conn['state'] != ConnectionState.CONNECTED:
                    conn['state'] = ConnectionState.CONNECTED
                    logger.info(f"✅ {name} восстановил соединение")
            
            return is_healthy
            
        except Exception as e:
            logger.error(f"Ошибка проверки здоровья {name}: {e}")
            return False
    
    def get_connection_state(self, name: str) -> ConnectionState:
        """Получение состояния соединения"""
        if name in self.connections:
            return self.connections[name]['state']
        return ConnectionState.ERROR
    
    def is_connection_healthy(self, name: str) -> bool:
        """Проверка, здорово ли соединение"""
        state = self.get_connection_state(name)
        return state == ConnectionState.CONNECTED
    
    def get_all_states(self) -> Dict[str, ConnectionState]:
        """Получение состояний всех соединений"""
        return {name: conn['state'] for name, conn in self.connections.items()}
    
    def set_state_callback(self, name: str, callback: Callable):
        """Установка callback для изменений состояния"""
        self.state_callbacks[name] = callback
    
    async def stop_all(self):
        """Остановка всех соединений"""
        for name, conn in self.connections.items():
            try:
                conn['client'].disconnect()
                conn['state'] = ConnectionState.DISCONNECTED
            except Exception as e:
                logger.error(f"Ошибка при остановке {name}: {e}")