#!/usr/bin/env python3
"""
Web Dashboard Server for NVDA Arbitrage Bot
Run this script to start the web dashboard without the trading bot.

Usage:
    python run_web_dashboard.py

The dashboard will be available at http://localhost:8080
"""
import asyncio
import sys
import os
import time
import random
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class MockWebSocketClient:
    """Mock WebSocket client for testing"""
    
    def __init__(self, name):
        self.name = name
        self.healthy = True
    
    def get_latest_data(self):
        base_price = 170.50
        return {
            'bid': base_price + random.uniform(-0.5, 0.5),
            'ask': base_price + random.uniform(0, 1),
            'last': base_price + random.uniform(-0.2, 0.2),
            'bids': [[base_price - 0.1, random.uniform(0.1, 1)], [base_price - 0.2, random.uniform(0.1, 1)]],
            'asks': [[base_price + 0.1, random.uniform(0.1, 1)], [base_price + 0.2, random.uniform(0.1, 1)]],
            'timestamp': int(time.time() * 1000),
        }
    
    def get_estimated_slippage(self):
        return {'buy': 0.0005, 'sell': 0.0005}


class MockArbitrageEngine:
    """Mock arbitrage engine for testing"""
    
    def __init__(self):
        self.positions = []
    
    def calculate_spreads(self, bitget_data, hyper_data, bitget_slippage=None, hyper_slippage=None):
        from core.arbitrage_engine import TradeDirection
        
        bg_bid = bitget_data.get('bid', 170)
        bg_ask = bitget_data.get('ask', 170.1)
        hl_bid = hyper_data.get('bid', 170.05)
        hl_ask = hyper_data.get('ask', 170.15)
        
        # B -> H: buy on Hyper, sell on Bitget
        b_to_h_gross = (hl_bid - bg_ask) / bg_ask * 100
        
        # H -> B: buy on Bitget, sell on Hyper
        h_to_b_gross = (bg_bid - hl_ask) / hl_ask * 100
        
        return {
            TradeDirection.B_TO_H: {'gross_spread': b_to_h_gross},
            TradeDirection.H_TO_B: {'gross_spread': h_to_b_gross},
        }
    
    def calculate_exit_spread_for_market(self, bitget_data, hyper_data, bitget_slippage=None, hyper_slippage=None):
        from core.arbitrage_engine import TradeDirection
        
        bg_bid = bitget_data.get('bid', 170)
        bg_ask = bitget_data.get('ask', 170.1)
        hl_bid = hyper_data.get('bid', 170.05)
        hl_ask = hyper_data.get('ask', 170.15)
        
        # Exit spreads (reverse of entry)
        b_to_h_exit = (bg_bid - hl_ask) / hl_ask * 100
        h_to_b_exit = (hl_bid - bg_ask) / bg_ask * 100
        
        return {
            TradeDirection.B_TO_H: b_to_h_exit,
            TradeDirection.H_TO_B: h_to_b_exit,
        }
    
    def get_open_positions(self):
        return []
    
    def has_open_positions(self):
        return False
    
    def get_spread_history(self, limit: int = 100):
        """Mock spread history for testing"""
        return {
            'labels': [],
            'datasets': {
                'entry_bh': [],
                'entry_hb': [],
                'exit_bh': [],
                'exit_hb': [],
            },
            'timestamps': [],
            'health': {
                'bitget': [],
                'hyper': [],
            }
        }


class MockPaperExecutor:
    """Mock paper executor for testing"""
    
    def __init__(self):
        self.portfolio = {
            'USDT': 950.0,
            'NVDA': 0.25,
        }
    
    def get_portfolio(self):
        return self.portfolio


class MockBot:
    """Mock bot for testing web dashboard without real connections"""
    
    def __init__(self):
        self.session_start = time.time() - 7200  # 2 hours ago
        self.trading_mode = type('TradingMode', (), {
            'ACTIVE': 'ACTIVE', 
            'PARTIAL': 'PARTIAL', 
            'STOPPED': 'STOPPED',
            'value': 'ACTIVE'
        })()
        self.bitget_healthy = True
        self.hyper_healthy = True
        self.session_stats = {
            'total_checks': 15234,
            'total_trades': 12,
            'time_in_active': 3600,
            'time_in_partial': 1800,
            'time_in_stopped': 600,
            'max_spread': 0.45,
            'avg_spread': 0.12,
            'positive_spreads': 450,
            'negative_spreads': 120,
        }
        self.best_spreads_session = {
            'best_entry_spread': 0.382,
            'best_entry_direction': 'B_TO_H',
            'best_entry_time': time.time() - 600,
            'best_exit_spread_overall': -0.125,
            'best_exit_direction': 'H_TO_B',
            'best_exit_time': time.time() - 300,
        }
        self.config = {
            'MIN_SPREAD_ENTER': 0.001,
            'MIN_SPREAD_EXIT': -0.0005,
        }
        
        # Mock components
        self.bitget_ws = MockWebSocketClient('Bitget')
        self.hyper_ws = MockWebSocketClient('Hyperliquid')
        self.arb_engine = MockArbitrageEngine()
        self.paper_executor = MockPaperExecutor()


async def main():
    print("=" * 50)
    print("NVDA Arbitrage Bot - Web Dashboard Server")
    print("=" * 50)
    print()
    print("This starts only the web dashboard (no trading).")
    print("Dashboard: http://localhost:8080")
    print("Press Ctrl+C to stop")
    print()
    
    try:
        from web_server import WebDashboardServer
        
        # Create mock bot
        bot = MockBot()
        
        # Create and start server
        server = WebDashboardServer(bot, host='0.0.0.0', port=8080)
        await server.start()
        
        print("Dashboard is running. Open http://localhost:8080 in your browser")
        print()
        
        # Keep running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
    except ImportError as e:
        print(f"Error: {e}")
        print("Install required packages: pip install aiohttp")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
