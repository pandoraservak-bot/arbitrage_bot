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
- **Spread Confirmation Delay**:
  - 1-second delay before opening position with spread reconfirmation
  - Prevents false signals from momentary spread spikes
  - Uses `_last_calculated_spreads` with 2s staleness check
  - Entry cancelled if spread drops below MIN_SPREAD_ENTER during delay
- **Real Execution Prices**:
  - Position now stores actual fill prices from `avg_price` field in exchange responses
  - Calculates real entry spread from actual execution prices
  - Logs comparison: expected vs actual prices and spreads
- **Bitget Private WebSocket Fix**:
  - Fixed authentication check: `str(code) == '0'` handles both string and numeric responses
- **HIP-3 Trading Implementation**:
  - xyz:NVDA is a HIP-3 (builder-deployed) perpetual on TradeXYZ DEX, NOT in standard Hyperliquid universe
  - HIP-3 DEX index: 1, Asset index: 2, Asset ID: 110002 (formula: 100000 + dex_index*10000 + asset_index)
  - SDK's high-level methods (market_open/order) don't support HIP-3 assets
  - Implemented raw signing API using `sign_l1_action()` with HIP-3 asset ID directly
  - Added `_execute_hip3_order()` method for HIP-3 order execution
  - Proper response parsing: checks statuses[] for errors/fills, only returns success when 'filled' present
  - Price rounded to 2 decimals, size to 3 decimals (xyz:NVDA szDecimals=3)
- **Order Size Update**:
  - MIN_ORDER_CONTRACTS increased from 0.01 to 0.06 (~$11 at $187) to meet Bitget's $5 minimum
  - MAX_POSITION_CONTRACTS increased from 0.02 to 0.2 for larger position capacity
- **Position Mode Tracking**:
  - Each position now records whether it was opened in "paper" or "live" mode
  - Position class has new `mode` field with default "paper" for backward compatibility
  - Cross-mode closing: Positions closed using the executor matching their creation mode, not current mode
  - UI displays mode badge ("Бумага"/"Реал") for each position with color styling
- **Hyperliquid SDK Fix**:
  - Fixed parameter from `coin=` to `name=` in `market_open()` and `order()` methods
- **Trading Mode Persistence**:
  - Mode (paper/live) now persists across bot restarts via `data/trading_mode.json`
  - `config.load_trading_mode()` loads saved mode on startup
  - `config.save_trading_mode()` saves mode on every change
  - LiveTradeExecutor auto-initializes on startup when mode is live
  - Frontend restores correct mode display (badge, portfolio panel) from server's `paper_or_live` field
- **Live Trading Executor Fix**:
  - Added `execute_fok_pair` method to LiveTradeExecutor (was missing, causing AttributeError)
  - Fixed executor selection in ArbitrageEngine to properly switch between paper and live executors
  - Entry and exit now check TRADING_MODE['LIVE_ENABLED'] and use appropriate executor
  - Note: Paper positions block live trading - close all paper positions before switching to live mode
- **Position Mode Display Fix**:
  - Added `mode` field to positions sent to frontend via WebSocket (was missing)
  - UI now correctly displays "Реал" badge for live positions instead of "Бумага"
- **Hyperliquid Order Execution**:
  - Increased slippage to 5% for aggressive IOC order execution (market-like behavior)
  - Note: Hyperliquid API only supports limit orders - IOC with aggressive price acts as market order
  - Order type always shows as "Limit" in exchange history (this is normal for IOC)
- **Live Portfolio Persistence Fix**:
  - Fixed live portfolio showing $0.00 after bot restart
  - Integrated `live_portfolio` into `full_update` payload using synchronous `get_ws_portfolio()` method
  - Removed async broadcast which had timing issues; now uses single unified payload
  - Frontend `renderFullUpdate()` processes `live_portfolio` from main data payload

## Previous Changes (Dec 29, 2025)
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
