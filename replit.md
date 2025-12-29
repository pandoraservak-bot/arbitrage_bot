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
│   ├── websocket_clients.py       # WebSocket connections for market data (prices)
│   ├── private_websocket_clients.py # Private WebSocket for account data streaming
│   ├── arbitrage_engine.py        # Spread calculation and trade logic
│   ├── risk_manager.py            # Risk management controls
│   ├── paper_executor.py          # Paper trading execution
│   ├── live_executor.py           # Live trading with exchange APIs
│   └── connection_manager.py      # Connection handling
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

## Live Trading Module
The bot supports both paper trading and live trading modes:

### Paper Trading (default)
- Uses `core/paper_executor.py` for simulated trades
- No real money involved, portfolio tracked locally

### Live Trading
- Uses `core/live_executor.py` with official exchange SDKs
- **Hyperliquid**: Uses `hyperliquid-python-sdk` for API trading
- **Bitget**: Uses REST API with HMAC signature authentication

### Required Secrets for Live Trading
Set these in Replit Secrets:
- `HYPERLIQUID_SECRET_KEY`: Your Hyperliquid wallet private key
- `HYPERLIQUID_ACCOUNT_ADDRESS`: Your Hyperliquid account address
- `BITGET_API_KEY`: Bitget API key
- `BITGET_SECRET_KEY`: Bitget secret key
- `BITGET_PASSPHRASE`: Bitget API passphrase

### Trading Mode Toggle
- Switch between Paper/Live mode via web dashboard
- Live mode shows API connection status (green = connected)
- Confirmation required before enabling live trading

## Recent Changes (Dec 29, 2025)
- **Spread History Chart Improvements**:
  - SpreadHistoryManager with deque storage (1000 points max) and JSON persistence
  - Chart.js annotation plugin for threshold lines (entry/exit targets)
  - Delta updates for efficient data transfer
  - Reset zoom button and CSV export functionality
  - Dynamic threshold line updates when configuration changes
- **24-Hour Spread Heatmap**:
  - Color-coded grid showing spread distribution by hour
  - Displays average spread, max spread, and data point count
  - `/api/heatmap` endpoint for hourly statistics
  - `/api/export-csv` endpoint for data export
- **UI Text in Russian**: All dashboard labels, buttons, and messages in Russian

## Previous Changes (Dec 27, 2025)
- **Market Status Display**: Added real-time Bitget NVDA market status indicator
  - Shows "ОТКРЫТ" (green) when market is trading normally
  - Shows "ЗАКРЫТ" (red) when market is closed/maintenance (weekends, holidays)
  - Status fetched from Bitget API `/api/v2/mix/market/contracts` endpoint
  - Cached for 60 seconds to reduce API calls

## Previous Changes (Dec 2025)
- **Private WebSocket Streaming**: Real-time account data via WebSocket instead of REST polling
  - Hyperliquid: `webData2` subscription for account state, positions, equity
  - Bitget: `account` and `positions` channels with authentication
  - Updates pushed instantly when data changes (vs 0.5s polling)
- **Live Portfolio Display**: Shows real balances from both exchanges
  - Separate cards for Hyperliquid and Bitget with equity, available, margin, positions
  - Combined totals with net P&L
  - Automatic switch between Paper/Live views when mode changes
- **Added Live Trading Module**: Created `core/live_executor.py` using official SDKs
- **Trading Mode Toggle**: Paper/Live switch in Configuration panel
- Added MIN_ORDER_INTERVAL setting for order frequency control
- Implemented partial entry/exit trading with contract-based sizing
- Added MAX_SLIPPAGE config with pre-entry validation
- Removed USD-based position limits (MAX_TRADE_LOSS, MAX_POSITION_USD)
- Added slippage warning toast notifications in web UI
- Updated Refresh button to reset session and enable trading
- Fixed CSP policy for Chart.js compatibility
