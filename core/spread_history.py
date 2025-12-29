# Spread History Manager - Хранение и управление историей спредов
import json
import os
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from collections import deque
import logging
import io

from config import DATA_DIR, TRADING_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class SpreadDataPoint:
    """Точка данных спреда для графика"""
    timestamp: float
    time_str: str  # Форматированное время для отображения
    entry_spread_bh: float  # Входной спред B→H
    entry_spread_hb: float  # Входной спред H→B
    exit_spread_bh: float   # Выходной спред B→H
    exit_spread_hb: float   # Выходной спред H→B
    best_entry_spread: float  # Лучший входной спред
    best_exit_spread: float   # Лучший выходной спред
    bitget_healthy: bool
    hyper_healthy: bool
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SpreadDataPoint':
        return cls(**data)


class SpreadHistoryManager:
    """Менеджер истории спредов для построения графиков"""
    
    def __init__(self, max_points: int = 1000, save_interval: int = 60):
        """
        Args:
            max_points: Максимальное количество точек в памяти
            save_interval: Интервал сохранения в файл (секунды)
        """
        self.max_points = max_points
        self.save_interval = save_interval
        self.history_file = os.path.join(DATA_DIR, "spreads_history.json")
        self.hourly_file = os.path.join(DATA_DIR, "hourly_stats.json")
        
        self._data: deque = deque(maxlen=max_points)
        
        self._last_save_time = 0
        self._lock = threading.Lock()
        
        self._last_sent_index = 0
        
        self._hourly_stats: Dict[int, Dict[str, Any]] = {
            h: {'count': 0, 'sum_entry_bh': 0.0, 'sum_entry_hb': 0.0, 
                'max_entry_bh': float('-inf'), 'max_entry_hb': float('-inf')} 
            for h in range(24)
        }
        
        self._load_history()
        self._load_hourly_stats()
        
        logger.info(f"SpreadHistoryManager initialized. Max points: {max_points}")
    
    def add_spreads(self, entry_spreads: Dict, exit_spreads: Dict,
                   bitget_healthy: bool, hyper_healthy: bool):
        """Добавление новой точки спредов"""
        now = time.time()
        current_hour = datetime.fromtimestamp(now).hour
        
        entry_bh = entry_spreads.get('B_TO_H', 0)
        entry_hb = entry_spreads.get('H_TO_B', 0)
        
        dp = SpreadDataPoint(
            timestamp=now,
            time_str=datetime.fromtimestamp(now).strftime('%H:%M:%S'),
            entry_spread_bh=entry_bh,
            entry_spread_hb=entry_hb,
            exit_spread_bh=exit_spreads.get('B_TO_H', 0),
            exit_spread_hb=exit_spreads.get('H_TO_B', 0),
            best_entry_spread=max(entry_bh, entry_hb),
            best_exit_spread=min(
                exit_spreads.get('B_TO_H', float('inf')),
                exit_spreads.get('H_TO_B', float('inf'))
            ) if all(v != float('inf') for v in exit_spreads.values()) else 0,
            bitget_healthy=bitget_healthy,
            hyper_healthy=hyper_healthy
        )
        
        with self._lock:
            self._data.append(dp)
            
            stats = self._hourly_stats[current_hour]
            stats['count'] += 1
            stats['sum_entry_bh'] += entry_bh
            stats['sum_entry_hb'] += entry_hb
            stats['max_entry_bh'] = max(stats['max_entry_bh'], entry_bh)
            stats['max_entry_hb'] = max(stats['max_entry_hb'], entry_hb)
        
        if now - self._last_save_time >= self.save_interval:
            self._save_history()
            self._save_hourly_stats()
            self._last_save_time = now
    
    def get_chart_data(self, limit: int = 100) -> Dict:
        """Получение данных для графика (последние N точек)"""
        with self._lock:
            data = list(self._data)[-limit:]
        
        return {
            'labels': [dp.time_str for dp in data],
            'datasets': {
                'entry_bh': [dp.entry_spread_bh for dp in data],
                'entry_hb': [dp.entry_spread_hb for dp in data],
                'exit_bh': [dp.exit_spread_bh for dp in data],
                'exit_hb': [dp.exit_spread_hb for dp in data],
                'best_entry': [dp.best_entry_spread for dp in data],
                'best_exit': [dp.best_exit_spread for dp in data],
            },
            'timestamps': [dp.timestamp for dp in data],
            'health': {
                'bitget': [dp.bitget_healthy for dp in data],
                'hyper': [dp.hyper_healthy for dp in data],
            }
        }
    
    def get_statistics(self) -> Dict:
        """Получение статистики спредов"""
        with self._lock:
            if not self._data:
                return {
                    'count': 0,
                    'avg_entry': 0,
                    'max_entry': 0,
                    'avg_exit': 0,
                    'min_exit': 0,
                    'positive_entries': 0,
                    'negative_exits': 0
                }
            
            best_entries = [dp.best_entry_spread for dp in self._data]
            best_exits = [dp.best_exit_spread for dp in self._data if dp.best_exit_spread != 0]
            
            return {
                'count': len(self._data),
                'avg_entry': sum(best_entries) / len(best_entries),
                'max_entry': max(best_entries) if best_entries else 0,
                'avg_exit': sum(best_exits) / len(best_exits) if best_exits else 0,
                'min_exit': min(best_exits) if best_exits else 0,
                'positive_entries': sum(1 for v in best_entries if v > 0),
                'negative_exits': sum(1 for v in best_exits if v < 0)
            }
    
    def _save_history(self):
        """Сохранение истории в файл"""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            
            with self._lock:
                data = [dp.to_dict() for dp in self._data]
            
            with open(self.history_file, 'w') as f:
                json.dump({
                    'last_saved': datetime.now().isoformat(),
                    'data': data
                }, f, indent=2)
            
            logger.debug(f"Saved {len(data)} spread history points")
        except Exception as e:
            logger.error(f"Error saving spread history: {e}")
    
    def _load_history(self):
        """Загрузка истории из файла"""
        try:
            if not os.path.exists(self.history_file):
                return
            
            with open(self.history_file, 'r') as f:
                raw = json.load(f)
            
            data = raw.get('data', [])
            if data:
                points = [SpreadDataPoint.from_dict(dp) for dp in data[-self.max_points:]]
                self._data = deque(points, maxlen=self.max_points)
                logger.info(f"Loaded {len(points)} spread history points")
        except Exception as e:
            logger.warning(f"Error loading spread history: {e}")
    
    def clear_history(self):
        """Очистка истории"""
        with self._lock:
            self._data.clear()
            self._last_sent_index = 0
            self._hourly_stats = {
                h: {'count': 0, 'sum_entry_bh': 0.0, 'sum_entry_hb': 0.0,
                    'max_entry_bh': float('-inf'), 'max_entry_hb': float('-inf')}
                for h in range(24)
            }
        logger.info("Spread history cleared")
    
    def get_full_chart_data(self, limit: int = 500) -> Dict:
        """Получение полных данных для графика (при первом подключении)"""
        with self._lock:
            data = list(self._data)[-limit:]
            self._last_sent_index = len(self._data)
        
        return {
            'is_full': True,
            'labels': [dp.time_str for dp in data],
            'datasets': {
                'entry_bh': [dp.entry_spread_bh for dp in data],
                'entry_hb': [dp.entry_spread_hb for dp in data],
                'exit_bh': [dp.exit_spread_bh for dp in data],
                'exit_hb': [dp.exit_spread_hb for dp in data],
            }
        }
    
    def get_delta_chart_data(self) -> Optional[Dict]:
        """Получение только новых точек с последнего запроса (для инкрементальных обновлений)"""
        with self._lock:
            current_len = len(self._data)
            
            if self._last_sent_index >= current_len:
                return None
            
            new_data = list(self._data)[self._last_sent_index:]
            self._last_sent_index = current_len
            
            if not new_data:
                return None
        
        return {
            'is_delta': True,
            'labels': [dp.time_str for dp in new_data],
            'datasets': {
                'entry_bh': [dp.entry_spread_bh for dp in new_data],
                'entry_hb': [dp.entry_spread_hb for dp in new_data],
                'exit_bh': [dp.exit_spread_bh for dp in new_data],
                'exit_hb': [dp.exit_spread_hb for dp in new_data],
            }
        }
    
    def get_heatmap_data(self) -> Dict[str, Any]:
        """Получение данных для тепловой карты по часам"""
        with self._lock:
            heatmap = {}
            for hour in range(24):
                stats = self._hourly_stats[hour]
                count = stats['count']
                if count > 0:
                    avg_bh = stats['sum_entry_bh'] / count
                    avg_hb = stats['sum_entry_hb'] / count
                    max_bh = stats['max_entry_bh'] if stats['max_entry_bh'] != float('-inf') else 0
                    max_hb = stats['max_entry_hb'] if stats['max_entry_hb'] != float('-inf') else 0
                    heatmap[str(hour)] = {
                        'avg_entry_bh': round(avg_bh, 4),
                        'avg_entry_hb': round(avg_hb, 4),
                        'best_avg': round(max(avg_bh, avg_hb), 4),
                        'max_entry': round(max(max_bh, max_hb), 4),
                        'count': count
                    }
                else:
                    heatmap[str(hour)] = {
                        'avg_entry_bh': 0,
                        'avg_entry_hb': 0,
                        'best_avg': 0,
                        'max_entry': 0,
                        'count': 0
                    }
            return heatmap
    
    def get_csv_export(self) -> str:
        """Экспорт истории в CSV формат"""
        with self._lock:
            lines = ['timestamp,time,entry_bh,entry_hb,exit_bh,exit_hb,best_entry,best_exit']
            for dp in self._data:
                lines.append(
                    f"{dp.timestamp},{dp.time_str},{dp.entry_spread_bh:.6f},"
                    f"{dp.entry_spread_hb:.6f},{dp.exit_spread_bh:.6f},"
                    f"{dp.exit_spread_hb:.6f},{dp.best_entry_spread:.6f},{dp.best_exit_spread:.6f}"
                )
            return '\n'.join(lines)
    
    def _save_hourly_stats(self):
        """Сохранение статистики по часам в файл"""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            
            with self._lock:
                serializable_stats = {}
                for hour, stats in self._hourly_stats.items():
                    serializable_stats[str(hour)] = {
                        'count': stats['count'],
                        'sum_entry_bh': stats['sum_entry_bh'],
                        'sum_entry_hb': stats['sum_entry_hb'],
                        'max_entry_bh': stats['max_entry_bh'] if stats['max_entry_bh'] != float('-inf') else 0,
                        'max_entry_hb': stats['max_entry_hb'] if stats['max_entry_hb'] != float('-inf') else 0
                    }
            
            with open(self.hourly_file, 'w') as f:
                json.dump({
                    'last_saved': datetime.now().isoformat(),
                    'stats': serializable_stats
                }, f, indent=2)
            
            logger.debug("Saved hourly stats")
        except Exception as e:
            logger.error(f"Error saving hourly stats: {e}")
    
    def _load_hourly_stats(self):
        """Загрузка статистики по часам из файла"""
        try:
            if not os.path.exists(self.hourly_file):
                return
            
            with open(self.hourly_file, 'r') as f:
                raw = json.load(f)
            
            saved_stats = raw.get('stats', {})
            for hour_str, stats in saved_stats.items():
                hour = int(hour_str)
                if 0 <= hour < 24:
                    self._hourly_stats[hour] = {
                        'count': stats.get('count', 0),
                        'sum_entry_bh': stats.get('sum_entry_bh', 0.0),
                        'sum_entry_hb': stats.get('sum_entry_hb', 0.0),
                        'max_entry_bh': stats.get('max_entry_bh', float('-inf')),
                        'max_entry_hb': stats.get('max_entry_hb', float('-inf'))
                    }
            
            logger.info("Loaded hourly stats")
        except Exception as e:
            logger.warning(f"Error loading hourly stats: {e}")
