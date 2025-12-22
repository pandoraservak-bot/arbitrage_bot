# core/__init__.py - обновленная версия
from .websocket_clients import BitgetWebSocketClient, HyperliquidWebSocketClient
from .hyperliquid_rest import HyperliquidRESTClient
from .risk_manager import RiskManager
from .paper_executor import PaperTradeExecutor
from .arbitrage_engine import ArbitrageEngine, Position, TradeDirection

__all__ = [
    'BitgetWebSocketClient',
    'HyperliquidWebSocketClient',
    'HyperliquidRESTClient',
    'RiskManager',
    'PaperTradeExecutor',
    'ArbitrageEngine',
    'Position',
    'TradeDirection'
]