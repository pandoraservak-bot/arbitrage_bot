# NVDA Futures Arbitrage Bot

## Overview
A Python-based arbitrage trading bot that monitors price spreads between Bitget and Hyperliquid exchanges for NVDA futures. It displays real-time spread analysis and trading opportunities in a console dashboard.

## Project Structure
```
├── main.py                 # Main entry point and bot logic
├── config.py               # Configuration settings for exchanges, trading, and display
├── core/
│   ├── websocket_clients.py # WebSocket connections to Bitget and Hyperliquid
│   ├── arbitrage_engine.py  # Spread calculation and trade logic
│   ├── risk_manager.py      # Risk management controls
│   ├── paper_executor.py    # Paper trading execution
│   └── connection_manager.py # Connection handling
├── utils/
│   └── helpers.py          # Utility functions
├── data/
│   ├── logs/               # Daily log files
│   ├── paper_portfolio.json # Paper trading portfolio state
│   └── session_stats.json  # Session statistics
└── requirements.txt        # Python dependencies
```

## Configuration
- Exchange settings are in `config.py`
- Trading parameters (spreads, fees, limits) configurable in `TRADING_CONFIG`
- Display modes: compact, ultra_compact, dashboard

## How to Run
The bot runs as a console application:
```
python main.py
```

## Dependencies
- websocket-client: WebSocket connections
- aiohttp: Async HTTP client
- pandas/numpy: Data processing
- colorama: Console colors
- python-dotenv: Environment variables

## Current State
- Paper trading mode (no real trades)
- Connects to Bitget and Hyperliquid WebSockets
- Displays real-time bid/ask prices and spread analysis
- Tracks best entry/exit spreads per session
