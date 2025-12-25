#!/usr/bin/env python3
"""
Web Dashboard Server for NVDA Arbitrage Bot
Run this script to start the web dashboard with REAL exchange connections.

Usage:
    python run_web_dashboard.py

The dashboard will be available at http://localhost:5000
"""
import asyncio
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.websocket_clients import BitgetWebSocketClient, HyperliquidWebSocketClient
from core.arbitrage_engine import ArbitrageEngine, TradeDirection
from core.paper_executor import PaperTradeExecutor
from core.risk_manager import RiskManager
from core.spread_history import SpreadHistoryManager


class RealBot:
    """Real bot with actual exchange connections"""
    
    def __init__(self, event_loop):
        self.session_start = time.time()
        self.trading_mode = type('TradingMode', (), {
            'ACTIVE': 'ACTIVE', 
            'PARTIAL': 'PARTIAL', 
            'STOPPED': 'STOPPED',
            'value': 'ACTIVE'
        })()
        self.bitget_healthy = False
        self.hyper_healthy = False
        self.session_stats = {
            'total_checks': 0,
            'total_trades': 0,
            'time_in_active': 0,
            'time_in_partial': 0,
            'time_in_stopped': 0,
            'max_spread': 0.0,
            'avg_spread': 0.0,
            'positive_spreads': 0,
            'negative_spreads': 0,
        }
        self.best_spreads_session = {
            'best_entry_spread': 0.0,
            'best_entry_direction': None,
            'best_entry_time': None,
            'best_exit_spread_overall': 0.0,
            'best_exit_direction': None,
            'best_exit_time': None,
        }
        self.config = {
            'MIN_SPREAD_ENTER': 0.001,
            'MIN_SPREAD_EXIT': -0.0005,
        }
        
        self.bitget_ws = BitgetWebSocketClient(symbol="NVDAUSDT", inst_type="USDT-FUTURES", event_loop=event_loop)
        self.hyper_ws = HyperliquidWebSocketClient(symbol="xyz:NVDA", event_loop=event_loop)
        
        self.paper_executor = PaperTradeExecutor()
        self.risk_manager = RiskManager()
        self.arb_engine = ArbitrageEngine(
            risk_manager=self.risk_manager,
            paper_executor=self.paper_executor,
            bot=self
        )
        self.spread_history = SpreadHistoryManager()
        
    def connect(self):
        """Connect to exchanges"""
        print("Connecting to Bitget...")
        bitget_ok = self.bitget_ws.start()
        self.bitget_healthy = bitget_ok
        print(f"  Bitget: {'Connected' if bitget_ok else 'Failed'}")
        
        print("Connecting to Hyperliquid...")
        hyper_ok = self.hyper_ws.start()
        self.hyper_healthy = hyper_ok
        print(f"  Hyperliquid: {'Connected' if hyper_ok else 'Failed'}")
        
        return bitget_ok or hyper_ok
    
    def disconnect(self):
        """Disconnect from exchanges"""
        self.bitget_ws.disconnect()
        self.hyper_ws.disconnect()


async def main():
    print("=" * 50)
    print("NVDA Arbitrage Bot - Web Dashboard Server")
    print("=" * 50)
    print()
    print("Connecting to REAL exchanges...")
    print()
    
    bot = None
    
    try:
        from web_server import WebDashboardServer
        
        loop = asyncio.get_event_loop()
        bot = RealBot(event_loop=loop)
        
        if not bot.connect():
            print("Warning: Could not connect to any exchange")
        
        await asyncio.sleep(2)
        
        server = WebDashboardServer(bot, host='0.0.0.0', port=5000)
        await server.start()
        
        print()
        print("Dashboard: http://localhost:5000")
        print("Press Ctrl+C to stop")
        print()
        
        while True:
            bot.bitget_healthy = bot.bitget_ws.is_healthy()
            bot.hyper_healthy = bot.hyper_ws.is_healthy()
            
            bitget_data = bot.bitget_ws.get_latest_data()
            hyper_data = bot.hyper_ws.get_latest_data()
            
            if bitget_data and hyper_data:
                bot.session_stats['total_checks'] += 1
                
                spreads = bot.arb_engine.calculate_spreads(bitget_data, hyper_data)
                
                b_to_h = spreads.get(TradeDirection.B_TO_H, {}).get('gross_spread', 0)
                h_to_b = spreads.get(TradeDirection.H_TO_B, {}).get('gross_spread', 0)
                best_spread = max(b_to_h, h_to_b)
                
                if best_spread > bot.best_spreads_session.get('best_entry_spread', 0):
                    bot.best_spreads_session['best_entry_spread'] = best_spread
                    bot.best_spreads_session['best_entry_direction'] = 'B_TO_H' if b_to_h > h_to_b else 'H_TO_B'
                    bot.best_spreads_session['best_entry_time'] = time.time()
                
                best_exit_spread = max(b_to_h, h_to_b)
                current_best_exit = bot.best_spreads_session.get('best_exit_spread_overall', 0)
                if best_exit_spread > current_best_exit:
                    bot.best_spreads_session['best_exit_spread_overall'] = best_exit_spread
                    bot.best_spreads_session['best_exit_direction'] = 'B_TO_H' if b_to_h > h_to_b else 'H_TO_B'
                    bot.best_spreads_session['best_exit_time'] = time.time()
                
                if best_spread > 0:
                    bot.session_stats['positive_spreads'] += 1
                else:
                    bot.session_stats['negative_spreads'] += 1
                
                if best_spread > bot.session_stats.get('max_spread', 0):
                    bot.session_stats['max_spread'] = best_spread
            
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        if bot:
            bot.disconnect()
    except ImportError as e:
        print(f"Error: {e}")
        print("Install required packages: pip install aiohttp")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        if bot:
            bot.disconnect()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
