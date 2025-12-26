# NVDA Futures Arbitrage Bot

## Overview
A Python-based arbitrage trading bot that monitors price spreads between Bitget and Hyperliquid exchanges for NVDA futures. It displays real-time spread analysis and trading opportunities via a web dashboard on port 5000.

## Project Structure
```
├── main.py                 # Main entry point with integrated web dashboard
├── config.py               # Configuration settings for exchanges, trading, and display
├── web_server.py           # Flask web server and WebSocket handler
├── web/
│   ├── index.html          # Dashboard HTML
│   ├── style.css           # Dashboard styles
│   └── app_v7.js           # Dashboard JavaScript (real-time updates)
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
- Key settings:
  - `MIN_SPREAD_ENTER`: Minimum gross spread to enter position (decimal, e.g., 0.001 = 0.1%)
  - `MIN_SPREAD_EXIT`: Minimum spread to exit position
  - `MAX_POSITION_CONTRACTS`: Maximum total position size in contracts
  - `MIN_ORDER_CONTRACTS`: Size of each partial entry/exit order
  - `MAX_SLIPPAGE`: Maximum allowed slippage before blocking entry (decimal)
  - `MAX_DAILY_LOSS`: Daily loss limit in USD

## Trading Logic
- **Partial Entry**: Bot enters positions with MIN_ORDER_CONTRACTS size, accumulating up to MAX_POSITION_CONTRACTS
- **Partial Exit**: Exits positions in MIN_ORDER_CONTRACTS increments
- **Slippage Check**: Before entry, validates slippage < MAX_SLIPPAGE; blocks entry and shows warning if exceeded
- **Risk Management**: Contract-based position limits (no USD limits for position sizing)

## Web Dashboard
The dashboard on port 5000 provides:
- Real-time bid/ask prices from both exchanges
- Current entry/exit spread percentages
- Position tracking and P&L
- Session statistics (best spreads, trade count)
- Risk configuration panel (editable thresholds)
- Toast notifications for slippage warnings
- Refresh button resets session and re-enables trading

## How to Run
```
python main.py
```

## Dependencies
- websocket-client: WebSocket connections
- aiohttp: Async HTTP client
- Flask: Web server
- flask-cors: CORS support
- colorama: Console colors
- python-dotenv: Environment variables

## Recent Changes (Dec 2025)
- Implemented partial entry/exit trading with contract-based sizing
- Added MAX_SLIPPAGE config with pre-entry validation
- Removed USD-based position limits (MAX_TRADE_LOSS, MAX_POSITION_USD)
- Added slippage warning toast notifications in web UI
- Updated Refresh button to reset session and enable trading
- Fixed CSP policy for Chart.js compatibility
