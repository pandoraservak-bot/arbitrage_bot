// NVDA Arbitrage Bot - Web Dashboard Client v2.0

// Global State
let modalCallback = null;
let lastUpdateTime = Date.now();
const tradeHistory = [];
const eventLog = [];
const MAX_TRADE_HISTORY = 100;
const MAX_EVENT_LOG = 200;

// Target editing state
let currentTargetType = null;

// Toast Notification System
class ToastNotification {
    constructor() {
        this.container = document.getElementById('toastContainer');
    }

    show(message, type = 'success', duration = 5000) {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        const icon = type === 'success' ? '✓' : type === 'warning' ? '⚠️' : '❌';
        
        // Create toast elements safely without innerHTML
        const iconSpan = document.createElement('span');
        iconSpan.className = 'toast-icon';
        iconSpan.textContent = icon;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'toast-content';
        
        const messageDiv = document.createElement('div');
        messageDiv.className = 'toast-message';
        messageDiv.textContent = message;
        
        const closeBtn = document.createElement('button');
        closeBtn.className = 'toast-close';
        closeBtn.setAttribute('data-action', 'close-toast');
        closeBtn.textContent = '×';
        
        contentDiv.appendChild(messageDiv);
        toast.appendChild(iconSpan);
        toast.appendChild(contentDiv);
        toast.appendChild(closeBtn);
        
        this.container.appendChild(toast);
        
        if (duration > 0) {
            setTimeout(() => {
                if (toast.parentElement) {
                    toast.remove();
                }
            }, duration);
        }
    }

    success(message) {
        this.show(message, 'success', 5000);
    }

    warning(message) {
        this.show(message, 'warning', 7000);
    }

    error(message) {
        this.show(message, 'error', 10000);
    }
}

// Event Logger
class EventLogger {
    constructor() {
        this.events = [];
        this.container = document.getElementById('eventLogList');
        this.filter = 'all';
    }

    addEvent(message, type = 'success') {
        const event = {
            message,
            type,
            timestamp: new Date()
        };
        
        this.events.unshift(event);
        
        if (this.events.length > MAX_EVENT_LOG) {
            this.events = this.events.slice(0, MAX_EVENT_LOG);
        }
        
        this.render();
        
        const logContent = this.container.closest('.event-log-content');
        if (logContent) {
            logContent.scrollTop = 0;
        }
    }

    render() {
        const filtered = this.filter === 'all' 
            ? this.events 
            : this.events.filter(e => e.type === this.filter);
        
        // Clear container
        this.container.textContent = '';
        
        if (filtered.length === 0) {
            const noEventsDiv = document.createElement('div');
            noEventsDiv.className = 'no-events';
            noEventsDiv.textContent = 'No events yet';
            this.container.appendChild(noEventsDiv);
            return;
        }
        
        // Create event items safely without innerHTML
        filtered.forEach(event => {
            const icon = event.type === 'success' ? '✓' : event.type === 'warning' ? '⚠️' : '❌';
            const time = event.timestamp.toLocaleTimeString();
            
            const itemDiv = document.createElement('div');
            itemDiv.className = `event-log-item ${event.type}`;
            
            const iconSpan = document.createElement('span');
            iconSpan.className = 'event-icon';
            iconSpan.textContent = icon;
            
            const contentDiv = document.createElement('div');
            contentDiv.className = 'event-content';
            
            const messageDiv = document.createElement('div');
            messageDiv.className = 'event-message';
            messageDiv.textContent = event.message;
            
            const timeDiv = document.createElement('div');
            timeDiv.className = 'event-time';
            timeDiv.textContent = time;
            
            contentDiv.appendChild(messageDiv);
            contentDiv.appendChild(timeDiv);
            itemDiv.appendChild(iconSpan);
            itemDiv.appendChild(contentDiv);
            
            this.container.appendChild(itemDiv);
        });
    }

    setFilter(filter) {
        this.filter = filter;
        this.render();
    }

    clear() {
        this.events = [];
        this.render();
    }
}

// Trade History Manager
class TradeHistoryManager {
    constructor() {
        this.trades = [];
        this.tbody = document.getElementById('tradeHistoryBody');
    }

    addTrade(trade) {
        this.trades.unshift(trade);
        
        if (this.trades.length > MAX_TRADE_HISTORY) {
            this.trades = this.trades.slice(0, MAX_TRADE_HISTORY);
        }
        
        this.render();
    }

    render() {
        // Clear tbody
        this.tbody.textContent = '';
        
        if (this.trades.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.setAttribute('colspan', '7');
            td.className = 'no-trades';
            td.textContent = 'No completed trades';
            tr.appendChild(td);
            this.tbody.appendChild(tr);
            return;
        }
        
        // Create trade rows safely without innerHTML
        this.trades.forEach(trade => {
            const profitClass = trade.profit >= 0 ? 'trade-profit-positive' : 'trade-profit-negative';
            const profitSign = trade.profit >= 0 ? '+' : '';
            
            const tr = document.createElement('tr');
            
            const idTd = document.createElement('td');
            idTd.textContent = `#${trade.id}`;
            
            const dirTd = document.createElement('td');
            dirTd.textContent = trade.direction;
            
            const entryTd = document.createElement('td');
            entryTd.textContent = `${trade.entry_spread}%`;
            
            const exitTd = document.createElement('td');
            exitTd.textContent = `${trade.exit_spread}%`;
            
            const profitTd = document.createElement('td');
            profitTd.className = profitClass;
            profitTd.textContent = `${profitSign}${trade.profit.toFixed(2)}`;
            
            const durationTd = document.createElement('td');
            durationTd.textContent = trade.duration;
            
            const timeTd = document.createElement('td');
            timeTd.textContent = trade.time;
            
            tr.appendChild(idTd);
            tr.appendChild(dirTd);
            tr.appendChild(entryTd);
            tr.appendChild(exitTd);
            tr.appendChild(profitTd);
            tr.appendChild(durationTd);
            tr.appendChild(timeTd);
            
            this.tbody.appendChild(tr);
        });
    }

    exportCSV() {
        if (this.trades.length === 0) {
            toast.warning('No trades to export');
            return;
        }
        
        const headers = ['ID', 'Direction', 'Entry Spread', 'Exit Spread', 'Profit', 'Duration', 'Time'];
        const rows = this.trades.map(t => [
            t.id,
            t.direction,
            t.entry_spread,
            t.exit_spread,
            t.profit.toFixed(2),
            t.duration,
            t.time
        ]);
        
        let csv = headers.join(',') + '\n';
        csv += rows.map(r => r.join(',')).join('\n');
        
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `trade_history_${new Date().toISOString().split('T')[0]}.csv`;
        a.click();
        URL.revokeObjectURL(url);
        
        toast.success('Trade history exported');
    }

    clear() {
        this.trades = [];
        this.render();
    }
}

// Dashboard Client
class DashboardClient {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.updateInterval = null;
        this.isConnected = false;
        this.lastUpdateTimestamp = Date.now();
        this.wsUptimeStart = Date.now();
        this.wsDowntime = 0;
        this.lastDisconnectTime = null;
        
        this.init();
    }

    init() {
        this.connect();
        this.setupEventListeners();
        this.startStatusUpdater();
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        console.log('Connecting to WebSocket:', wsUrl);
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.isConnected = true;
            this.reconnectAttempts = 0;
            this.updateModeBadge('connected');
            this.requestFullUpdate();
            
            if (this.lastDisconnectTime) {
                const downtime = Date.now() - this.lastDisconnectTime;
                this.wsDowntime += downtime;
                this.lastDisconnectTime = null;
            }
            
            eventLogger.addEvent('WebSocket connected', 'success');
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
                this.lastUpdateTimestamp = Date.now();
            } catch (e) {
                console.error('Error parsing message:', e);
            }
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.isConnected = false;
            this.updateModeBadge('disconnected');
            this.lastDisconnectTime = Date.now();
            eventLogger.addEvent('WebSocket disconnected', 'error');
            this.attemptReconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.isConnected = false;
        };
    }

    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            this.updateModeBadge('reconnecting');
            setTimeout(() => this.connect(), delay);
        } else {
            console.error('Max reconnection attempts reached');
            this.updateModeBadge('failed');
            eventLogger.addEvent('Connection failed - max retries reached', 'error');
        }
    }

    handleMessage(data) {
        if (!data) return;
        
        const type = data.type;
        
        switch (type) {
            case 'full_update':
                this.renderFullUpdate(data.payload);
                break;
            case 'status':
                this.updateStatus(data.payload);
                break;
            case 'spread':
                this.updateSpread(data.payload);
                break;
            case 'positions':
                this.updatePositions(data.payload);
                break;
            case 'portfolio':
                this.updatePortfolio(data.payload);
                break;
            case 'records':
                this.updateRecords(data.payload);
                break;
            case 'exit_spreads':
                this.updateExitSpreads(data.payload);
                break;
            case 'command_result':
                this.handleCommandResult(data);
                break;
            case 'event':
                this.handleEvent(data);
                break;
            case 'config':
                this.updateConfig(data.payload);
                break;
            case 'trading_mode':
                this.handleTradingModeChange(data.payload);
                break;
            case 'live_portfolio':
                this.updateLivePortfolio(data.payload);
                break;
            case 'pong':
                break;
            default:
                console.log('Unknown message type:', type);
        }
    }

    handleCommandResult(data) {
        console.log('[handleCommandResult] data:', data);
        const result = data.payload || data;
        console.log('[handleCommandResult] result:', result);
        if (result.success) {
            toast.success(result.message || 'Command successful');
            if (result.event_type) {
                eventLogger.addEvent(result.message, 'success');
            }
            this.updateBotStatusFromCommand(result.message);
        } else {
            toast.error(result.error || 'Command failed');
            eventLogger.addEvent(result.error || 'Command failed', 'error');
        }
    }

    updateBotStatusFromCommand(message) {
        const badge = document.getElementById('botStatusBadge');
        if (!badge) return;
        
        if (message && message.toLowerCase().includes('pause')) {
            badge.textContent = '⏸️ PAUSED';
            badge.className = 'bot-status-badge status-paused';
        } else if (message && message.toLowerCase().includes('stop')) {
            badge.textContent = '⏹️ STOPPED';
            badge.className = 'bot-status-badge status-stopped';
        } else if (message && message.toLowerCase().includes('start')) {
            badge.textContent = '▶️ ACTIVE';
            badge.className = 'bot-status-badge status-active';
        }
    }

    updateBotStatusBadge(data) {
        const badge = document.getElementById('botStatusBadge');
        if (!badge) return;
        
        const tradingEnabled = data.trading_enabled !== false;
        
        if (!tradingEnabled) {
            badge.textContent = '⏸️ PAUSED';
            badge.className = 'bot-status-badge status-paused';
        } else if (data.trading_mode === 'stopped') {
            badge.textContent = '⏹️ STOPPED';
            badge.className = 'bot-status-badge status-stopped';
        } else {
            badge.textContent = '▶️ ACTIVE';
            badge.className = 'bot-status-badge status-active';
        }
    }

    handleEvent(data) {
        eventLogger.addEvent(data.message, data.event_type || 'success');
        
        if (data.event_type === 'warning') {
            toast.warning(data.message);
        } else if (data.event_type === 'error') {
            toast.error(data.message);
        }
    }

    renderFullUpdate(data) {
        if (!data) return;
        
        this.updateRuntime(data.runtime);
        
        if (data.timestamp) {
            document.getElementById('serverTime').textContent = data.timestamp;
        }
        
        this.updateStatus(data);
        this.updatePrices(data);
        this.updateSpread(data);
        this.updateExitSpreads(data);
        this.updateRecords(data);
        this.updatePortfolio(data);
        this.updatePositions(data);
        this.updateStats(data);
        this.updateConfig(data);
        this.updateRiskStatus(data);
        
        // Handle warnings (slippage, risk, etc.)
        if (data.warnings && data.warnings.length > 0) {
            this.handleWarnings(data.warnings);
        }
        
        // Update total position contracts display
        if (data.total_position_contracts !== undefined) {
            const el = document.getElementById('totalPositionContracts');
            if (el) {
                el.textContent = data.total_position_contracts.toFixed(4);
            }
        }
        
        if (data.spread_chart_data) {
            updateSpreadChart(data.spread_chart_data);
        }
        
        document.getElementById('lastUpdate').textContent = 
            `Last update: ${new Date().toLocaleTimeString()}`;
    }
    
    handleWarnings(warnings) {
        for (const warning of warnings) {
            if (warning.type === 'slippage_warning') {
                toast.warning(`Slippage: ${warning.message}`);
            } else {
                toast.warning(warning.message || 'Unknown warning');
            }
        }
    }

    updateStatus(data) {
        if (!data) return;
        
        const mode = data.trading_mode || 'STOPPED';
        const tradingEnabled = data.trading_enabled !== false;
        this.updateModeBadge(mode.toLowerCase(), tradingEnabled);
        
        const bitgetHealthy = data.bitget_healthy || false;
        const hyperHealthy = data.hyper_healthy || false;
        
        const bitgetDot = document.getElementById('bitgetDot');
        const hyperDot = document.getElementById('hyperDot');
        
        bitgetDot.className = `status-dot ${bitgetHealthy ? 'healthy' : 'unhealthy'}`;
        hyperDot.className = `status-dot ${hyperHealthy ? 'healthy' : 'unhealthy'}`;
        
        if (data.bitget_latency !== undefined) {
            document.getElementById('bitgetLatency').textContent = `${data.bitget_latency}ms`;
        }
        
        if (data.hyper_latency !== undefined) {
            document.getElementById('hyperLatency').textContent = `${data.hyper_latency}ms`;
        }
        
        const marketStatusEl = document.getElementById('bitgetMarketStatus');
        if (marketStatusEl && data.market_status !== undefined) {
            const status = data.market_status;
            marketStatusEl.className = 'market-status';
            if (status === 'normal') {
                marketStatusEl.textContent = 'ОТКРЫТ';
                marketStatusEl.classList.add('market-open');
            } else if (status === 'maintain') {
                marketStatusEl.textContent = 'ЗАКРЫТ';
                marketStatusEl.classList.add('market-closed');
            } else {
                marketStatusEl.textContent = '--';
                marketStatusEl.classList.add('market-unknown');
            }
        }
        
        document.getElementById('totalTrades').textContent = 
            (data.session_stats?.total_trades || 0).toLocaleString();
        document.getElementById('totalChecks').textContent = 
            (data.session_stats?.total_checks || 0).toLocaleString();
    }

    updateRuntime(seconds) {
        if (seconds === undefined || seconds === null) return;
        
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        
        document.getElementById('runtime').textContent = 
            `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    updateModeBadge(mode, tradingEnabled = true) {
        const badge = document.getElementById('modeBadge');
        badge.className = 'mode-badge';
        
        if (!tradingEnabled && mode === 'active') {
            badge.textContent = '⏸️ PAUSED';
            badge.classList.add('paused');
            return;
        }
        
        switch (mode) {
            case 'active':
                badge.textContent = '▶️ ACTIVE';
                badge.classList.add('active');
                break;
            case 'partial':
                badge.textContent = '● PARTIAL';
                badge.classList.add('partial');
                break;
            case 'stopped':
                badge.textContent = '⏹️ STOPPED';
                badge.classList.add('stopped');
                break;
            case 'paused':
                badge.textContent = '⏸️ PAUSED';
                badge.classList.add('paused');
                break;
            case 'connecting':
                badge.textContent = 'CONNECTING...';
                break;
            case 'reconnecting':
                badge.textContent = 'RECONNECTING...';
                break;
            case 'disconnected':
                badge.textContent = 'DISCONNECTED';
                badge.classList.add('stopped');
                break;
            case 'failed':
                badge.textContent = 'CONNECTION FAILED';
                badge.classList.add('stopped');
                break;
            default:
                badge.textContent = mode.toUpperCase();
        }
    }

    updatePrices(data) {
        if (!data) return;
        
        const bitget = data.bitget_data || {};
        const hyper = data.hyper_data || {};
        
        if (bitget.bid && bitget.ask) {
            const avgPrice = (bitget.bid + bitget.ask) / 2;
            document.getElementById('bitgetPrice').textContent = `$${avgPrice.toFixed(2)}`;
            document.getElementById('bitgetBid').textContent = `$${bitget.bid.toFixed(2)}`;
            document.getElementById('bitgetAsk').textContent = `$${bitget.ask.toFixed(2)}`;
        }
        
        if (hyper.bid && hyper.ask) {
            const avgPrice = (hyper.bid + hyper.ask) / 2;
            document.getElementById('hyperPrice').textContent = `$${avgPrice.toFixed(2)}`;
            document.getElementById('hyperBid').textContent = `$${hyper.bid.toFixed(2)}`;
            document.getElementById('hyperAsk').textContent = `$${hyper.ask.toFixed(2)}`;
        }
    }

    updateSpread(data) {
        if (!data) return;

        const spreads = data.spreads || {};

        // Debug (throttled)
        const now = Date.now();
        if (!this._lastSpreadsConsoleLog || now - this._lastSpreadsConsoleLog > 5000) {
            console.log('[dashboard] updateSpread payload:', { spreads, best_entry_spread: data.best_entry_spread, best_entry_direction: data.best_entry_direction });
            this._lastSpreadsConsoleLog = now;
        }

        const bhObj = spreads.b_to_h || spreads.B_TO_H || spreads['B_TO_H'] || spreads['B→H'] || null;
        const hbObj = spreads.h_to_b || spreads.H_TO_B || spreads['H_TO_B'] || spreads['H→B'] || null;

        const bhSpread = bhObj?.gross_spread;
        if (bhSpread !== undefined) {
            document.getElementById('spreadBH').textContent = `${bhSpread.toFixed(3)}%`;
            this.updateSpreadBar('spreadBarBH', bhSpread);
        }

        const hbSpread = hbObj?.gross_spread;
        if (hbSpread !== undefined) {
            document.getElementById('spreadHB').textContent = `${hbSpread.toFixed(3)}%`;
            this.updateSpreadBar('spreadBarHB', hbSpread);
        }

        const bestEntry = data.best_entry_spread;
        const bestDirection = data.best_entry_direction;
        if (bestEntry !== undefined && bestEntry !== null) {
            const bestEl = document.getElementById('bestEntry');
            bestEl.textContent = `${bestEntry.toFixed(3)}%`;
            bestEl.className = `best-value ${bestEntry >= 0.1 ? 'value-positive' : bestEntry > 0 ? 'value-neutral' : 'value-negative'}`;

            const dirEl = document.getElementById('bestEntryDirection');
            if (bestDirection) {
                const dirLabel = bestDirection === 'B_TO_H' ? 'B → H' : bestDirection === 'H_TO_B' ? 'H → B' : bestDirection;
                dirEl.textContent = dirLabel;
            }
        }

        const target = data.config?.MIN_SPREAD_ENTER * 100;
        if (target !== undefined && target !== null) {
            document.getElementById('spreadTarget').textContent = target.toFixed(2);
        }
    }

    updateSpreadBar(elementId, value) {
        const bar = document.getElementById(elementId);
        if (!bar) return;
        
        const maxPercent = 1.0;
        const width = Math.min(Math.abs(value) / maxPercent * 100, 100);
        bar.style.width = `${width}%`;
        
        bar.className = 'spread-bar-fill';
        if (value >= 0.3) {
            bar.classList.add('good');
        } else if (value > 0) {
            bar.classList.add('low');
        } else {
            bar.classList.add('negative');
        }
    }

    updateExitSpreads(data) {
        if (!data) return;

        const exitSpreads = data.exit_spreads || {};

        // Debug (throttled)
        const now = Date.now();
        if (!this._lastExitSpreadsConsoleLog || now - this._lastExitSpreadsConsoleLog > 5000) {
            console.log('[dashboard] updateExitSpreads payload:', { exit_spreads: exitSpreads, best_exit_overall: data.best_exit_overall });
            this._lastExitSpreadsConsoleLog = now;
        }

        const bhExit = exitSpreads.b_to_h ?? exitSpreads.B_TO_H ?? exitSpreads['B_TO_H'] ?? exitSpreads['B→H'];
        const hbExit = exitSpreads.h_to_b ?? exitSpreads.H_TO_B ?? exitSpreads['H_TO_B'] ?? exitSpreads['H→B'];

        if (bhExit !== undefined && bhExit !== null) {
            document.getElementById('marketExitBH').textContent = `${bhExit.toFixed(3)}%`;
            document.getElementById('marketExitBH').className = `exit-value ${this.getExitSpreadClass(bhExit)}`;
        }

        if (hbExit !== undefined && hbExit !== null) {
            document.getElementById('marketExitHB').textContent = `${hbExit.toFixed(3)}%`;
            document.getElementById('marketExitHB').className = `exit-value ${this.getExitSpreadClass(hbExit)}`;
        }

        const bestExit = data.best_exit_overall;
        if (bestExit !== undefined && bestExit !== null) {
            const bestEl = document.getElementById('bestMarketExit');
            bestEl.textContent = `${bestExit.toFixed(3)}%`;
            bestEl.className = `best-value ${this.getExitSpreadClass(bestExit)}`;
        }

        const exitTarget = data.config?.MIN_SPREAD_EXIT * 100;
        if (exitTarget !== undefined && exitTarget !== null) {
            document.getElementById('exitTarget').textContent = exitTarget.toFixed(2);
        }
    }

    getExitSpreadClass(spread) {
        if (spread <= -0.1) return 'value-positive';
        if (spread <= 0) return 'value-neutral';
        return 'value-negative';
    }

    updateRecords(data) {
        if (!data) return;
        
        const bestEntry = data.best_entry_spread;
        if (bestEntry !== undefined && bestEntry > 0) {
            document.getElementById('bestEntryRecord').textContent = `${bestEntry.toFixed(3)}%`;
            
            const entryTime = data.best_entry_time;
            if (entryTime) {
                const ago = this.formatTimeAgo(entryTime);
                document.getElementById('bestEntryTime').textContent = ago;
            }
        } else {
            document.getElementById('bestEntryRecord').textContent = '---';
            document.getElementById('bestEntryTime').textContent = '---';
        }
        
        const bestExit = data.best_exit_overall;
        if (bestExit !== undefined && bestExit !== Infinity) {
            document.getElementById('bestExitRecord').textContent = `${bestExit.toFixed(3)}%`;
            
            const exitTime = data.best_exit_time;
            if (exitTime) {
                const ago = this.formatTimeAgo(exitTime);
                document.getElementById('bestExitTime').textContent = ago;
            }
        } else {
            document.getElementById('bestExitRecord').textContent = '---';
            document.getElementById('bestExitTime').textContent = '---';
        }
    }

    updatePortfolio(data) {
        if (!data) return;
        
        const portfolio = data.portfolio || {};
        const usdt = portfolio.USDT || 0;
        const nvda = portfolio.NVDA || 0;
        
        document.getElementById('portfolioUSDT').textContent = `$${usdt.toFixed(2)}`;
        document.getElementById('portfolioNVDA').textContent = nvda.toFixed(4);
        
        const totalValue = data.total_value || 0;
        const pnl = data.pnl || 0;
        
        document.getElementById('totalValue').textContent = `$${totalValue.toFixed(2)}`;
        
        const pnlEl = document.getElementById('pnlValue');
        pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
        pnlEl.className = `total-value ${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`;
    }

    handleTradingModeChange(data) {
        if (!data) return;
        
        const mode = data.mode;
        const status = data.live_executor_status || {};
        
        const badge = document.getElementById('portfolioModeBadge');
        const paperPortfolio = document.getElementById('paperPortfolio');
        const livePortfolio = document.getElementById('livePortfolio');
        
        if (mode === 'live') {
            currentTradingMode = 'live';
            badge.textContent = 'Live';
            badge.className = 'portfolio-mode-badge live';
            paperPortfolio.style.display = 'none';
            livePortfolio.style.display = 'block';
            
            document.getElementById('modePaper').classList.remove('active');
            document.getElementById('modeLive').classList.add('active');
            
            const hlStatus = document.getElementById('hlLiveStatus');
            const bgStatus = document.getElementById('bgLiveStatus');
            hlStatus.className = 'exchange-status ' + (status.hyperliquid_connected ? 'connected' : 'disconnected');
            bgStatus.className = 'exchange-status ' + (status.bitget_connected ? 'connected' : 'disconnected');
        } else {
            currentTradingMode = 'paper';
            badge.textContent = 'Paper';
            badge.className = 'portfolio-mode-badge paper';
            paperPortfolio.style.display = 'block';
            livePortfolio.style.display = 'none';
            
            document.getElementById('modePaper').classList.add('active');
            document.getElementById('modeLive').classList.remove('active');
        }
    }

    updateLivePortfolio(data) {
        if (!data) return;
        
        const hl = data.hyperliquid || {};
        const bg = data.bitget || {};
        const combined = data.combined || {};
        
        const hlStatus = document.getElementById('hlLiveStatus');
        const bgStatus = document.getElementById('bgLiveStatus');
        hlStatus.className = 'exchange-status ' + (hl.connected ? 'connected' : 'disconnected');
        bgStatus.className = 'exchange-status ' + (bg.connected ? 'connected' : 'disconnected');
        
        if (hl.connected) {
            document.getElementById('hlEquity').textContent = `$${(hl.equity || 0).toFixed(2)}`;
            document.getElementById('hlAvailable').textContent = `$${(hl.available || 0).toFixed(2)}`;
            document.getElementById('hlMargin').textContent = `$${(hl.margin_used || 0).toFixed(2)}`;
            
            const hlPos = hl.nvda_position;
            const hlPosEl = document.getElementById('hlNvdaPos');
            if (hlPos && hlPos.size !== 0) {
                hlPosEl.textContent = hlPos.size.toFixed(4);
                hlPosEl.className = 'balance-value ' + (hlPos.size < 0 ? 'short' : '');
            } else {
                hlPosEl.textContent = '0.0000';
                hlPosEl.className = 'balance-value';
            }
        }
        
        if (bg.connected) {
            document.getElementById('bgEquity').textContent = `$${(bg.equity || 0).toFixed(2)}`;
            document.getElementById('bgAvailable').textContent = `$${(bg.available || 0).toFixed(2)}`;
            document.getElementById('bgMargin').textContent = `$${(bg.margin_used || 0).toFixed(2)}`;
            
            const bgPos = bg.nvda_position;
            const bgPosEl = document.getElementById('bgNvdaPos');
            if (bgPos && bgPos.size !== 0) {
                bgPosEl.textContent = bgPos.size.toFixed(4);
                bgPosEl.className = 'balance-value ' + (bgPos.size < 0 ? 'short' : '');
            } else {
                bgPosEl.textContent = '0.0000';
                bgPosEl.className = 'balance-value';
            }
        }
        
        document.getElementById('combinedEquity').textContent = `$${(combined.total_equity || 0).toFixed(2)}`;
        
        const pnl = combined.total_pnl || 0;
        const pnlEl = document.getElementById('combinedPnl');
        pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
        pnlEl.className = `total-value ${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`;
    }

    updatePositions(data) {
        if (!data) return;
        
        const positions = data.positions || [];
        const positionsList = document.getElementById('positionsList');
        document.getElementById('positionsCount').textContent = positions.length;
        
        // Clear positions list
        positionsList.textContent = '';
        
        if (positions.length === 0) {
            const noPositionsDiv = document.createElement('div');
            noPositionsDiv.className = 'no-positions';
            noPositionsDiv.textContent = 'No open positions';
            positionsList.appendChild(noPositionsDiv);
            return;
        }
        
        // Create position items safely without innerHTML
        positions.forEach(pos => {
            const dirCode = pos.direction || pos.direction_label;
            const isBtoH = dirCode === 'B_TO_H' || dirCode === 'B→H' || dirCode === 'B->H';
            const dirClass = isBtoH ? 'b-to-h' : 'h-to-b';
            const dirLabel = isBtoH ? 'B → H' : 'H → B';
            
            let statusClass = 'normal';
            let statusText = 'Active';
            
            if (pos.should_close) {
                statusClass = 'ready';
                statusText = 'Ready!';
            } else if (pos.current_exit_spread >= pos.exit_target) {
                statusClass = 'warning';
                statusText = 'Target';
            }
            
            // Create position item container
            const positionItem = document.createElement('div');
            positionItem.className = `position-item ${dirClass}`;
            
            // Position ID
            const positionId = document.createElement('span');
            positionId.className = 'position-id';
            positionId.textContent = `#${pos.id}`;
            
            // Position direction
            const positionDir = document.createElement('span');
            positionDir.className = 'position-direction';
            positionDir.textContent = dirLabel;
            
            // Position details container
            const detailsDiv = document.createElement('div');
            detailsDiv.className = 'position-details';
            
            // Age detail
            const ageDetail = document.createElement('div');
            ageDetail.className = 'position-detail';
            const ageLabel = document.createElement('span');
            ageLabel.className = 'position-detail-label';
            ageLabel.textContent = 'Age:';
            const ageValue = document.createElement('span');
            ageValue.className = 'position-detail-value';
            ageValue.textContent = pos.age || '--';
            ageDetail.appendChild(ageLabel);
            ageDetail.appendChild(ageValue);
            
            // Exit spread detail
            const exitDetail = document.createElement('div');
            exitDetail.className = 'position-detail';
            const exitLabel = document.createElement('span');
            exitLabel.className = 'position-detail-label';
            exitLabel.textContent = 'Exit:';
            const exitValue = document.createElement('span');
            exitValue.className = 'position-detail-value';
            exitValue.textContent = `${pos.exit_spread.toFixed(3)}%`;
            exitDetail.appendChild(exitLabel);
            exitDetail.appendChild(exitValue);
            
            // Target detail (clickable button)
            const targetDetail = document.createElement('div');
            targetDetail.className = 'position-detail';
            const targetLabel = document.createElement('span');
            targetLabel.className = 'position-detail-label';
            targetLabel.textContent = 'Target:';
            
            const targetBtn = document.createElement('button');
            targetBtn.className = 'target-badge';
            targetBtn.setAttribute('data-position-target', '');
            targetBtn.setAttribute('data-position-id', pos.id);
            targetBtn.setAttribute('data-current-value', pos.exit_target.toFixed(3));
            targetBtn.textContent = `>=${pos.exit_target.toFixed(3)}%`;
            
            targetDetail.appendChild(targetLabel);
            targetDetail.appendChild(targetBtn);
            
            detailsDiv.appendChild(ageDetail);
            detailsDiv.appendChild(exitDetail);
            detailsDiv.appendChild(targetDetail);
            
            // Exit status
            const exitStatus = document.createElement('span');
            exitStatus.className = `exit-status ${statusClass}`;
            exitStatus.textContent = statusText;
            
            // Close button
            const closeBtn = document.createElement('button');
            closeBtn.className = 'btn btn-close-position';
            closeBtn.setAttribute('data-action', 'close-position');
            closeBtn.setAttribute('data-position-id', pos.id);
            closeBtn.textContent = '❌ Close';
            
            // Assemble position item
            positionItem.appendChild(positionId);
            positionItem.appendChild(positionDir);
            positionItem.appendChild(detailsDiv);
            positionItem.appendChild(exitStatus);
            positionItem.appendChild(closeBtn);
            
            positionsList.appendChild(positionItem);
        });
    }

    updateStats(data) {
        if (!data) return;
        
        const stats = data.session_stats || {};
        const runtime = data.runtime || 1;
        
        const activePct = (stats.time_in_active || 0) / runtime * 100;
        const partialPct = (stats.time_in_partial || 0) / runtime * 100;
        
        document.getElementById('activeTime').textContent = `${activePct.toFixed(1)}%`;
        document.getElementById('partialTime').textContent = `${partialPct.toFixed(1)}%`;
        
        const maxSpread = stats.max_spread || 0;
        const avgSpread = stats.avg_spread || 0;
        
        document.getElementById('maxSpread').textContent = `${maxSpread.toFixed(3)}%`;
        document.getElementById('avgSpread').textContent = `${avgSpread.toFixed(3)}%`;
    }

    updateConfig(data) {
        if (!data || !data.config) return;
        
        const config = data.config;
        
        if (config.MIN_SPREAD_ENTER !== undefined) {
            const input = document.getElementById('minSpreadEnter');
            if (input && !input.matches(':focus')) {
                input.value = (config.MIN_SPREAD_ENTER * 100).toFixed(2);
            }
        }
        
        if (config.MIN_SPREAD_EXIT !== undefined) {
            const input = document.getElementById('minSpreadExit');
            if (input && !input.matches(':focus')) {
                input.value = (config.MIN_SPREAD_EXIT * 100).toFixed(2);
            }
        }
        
        if (config.MAX_POSITION_AGE_HOURS !== undefined) {
            const input = document.getElementById('maxPositionAge');
            if (input && !input.matches(':focus')) {
                input.value = config.MAX_POSITION_AGE_HOURS;
            }
        }
        
        if (config.MAX_CONCURRENT_POSITIONS !== undefined) {
            const input = document.getElementById('maxConcurrentPos');
            if (input && !input.matches(':focus')) {
                input.value = config.MAX_CONCURRENT_POSITIONS;
            }
        }
        
        if (config.DAILY_LOSS_LIMIT !== undefined) {
            const input = document.getElementById('dailyLossLimit');
            if (input && !input.matches(':focus')) {
                input.value = config.DAILY_LOSS_LIMIT;
            }
        }
        
        if (config.MAX_POSITION_CONTRACTS !== undefined) {
            const input = document.getElementById('maxPositionSize');
            if (input && !input.matches(':focus')) {
                input.value = config.MAX_POSITION_CONTRACTS;
            }
        }
        
        if (config.MIN_ORDER_CONTRACTS !== undefined) {
            const input = document.getElementById('minOrderContracts');
            if (input && !input.matches(':focus')) {
                input.value = config.MIN_ORDER_CONTRACTS;
            }
        }
        
        if (config.MAX_SLIPPAGE !== undefined) {
            const input = document.getElementById('maxSlippage');
            if (input && !input.matches(':focus')) {
                input.value = (config.MAX_SLIPPAGE * 100).toFixed(2);
            }
        }
        
        if (config.MIN_ORDER_INTERVAL !== undefined) {
            const input = document.getElementById('minOrderInterval');
            if (input && !input.matches(':focus')) {
                input.value = config.MIN_ORDER_INTERVAL;
            }
        }
        
        updateChartThresholds(config);
    }

    updateRiskStatus(data) {
        if (!data) return;
        
        const dailyLoss = data.daily_loss || 0;
        const dailyLimit = data.config?.DAILY_LOSS_LIMIT || 1000;
        
        document.getElementById('currentDailyLoss').textContent = `$${Math.abs(dailyLoss).toFixed(2)}`;
        
        const pct = Math.min((Math.abs(dailyLoss) / dailyLimit) * 100, 100);
        const bar = document.getElementById('riskProgressBar');
        bar.style.width = `${pct}%`;
    }

    startStatusUpdater() {
        setInterval(() => {
            const now = Date.now();
            const elapsed = (now - this.lastUpdateTimestamp) / 1000;
            const lastUpdateEl = document.getElementById('lastUpdateStatus');
            if (lastUpdateEl) {
                if (elapsed < 60) {
                    lastUpdateEl.textContent = `${elapsed.toFixed(1)}s ago`;
                } else {
                    lastUpdateEl.textContent = `${(elapsed / 60).toFixed(1)}m ago`;
                }
            }
            
            const totalTime = now - this.wsUptimeStart;
            const activeTime = totalTime - this.wsDowntime - (this.lastDisconnectTime ? (now - this.lastDisconnectTime) : 0);
            const uptime = (activeTime / totalTime) * 100;
            const uptimeEl = document.getElementById('wsUptime');
            if (uptimeEl) {
                uptimeEl.textContent = `${uptime.toFixed(1)}%`;
            }
        }, 1000);
    }

    formatTimeAgo(timestamp) {
        const now = Date.now() / 1000;
        const diff = now - timestamp;
        
        if (diff < 60) return `${Math.floor(diff)}s ago`;
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        return `${Math.floor(diff / 3600)}h ago`;
    }

    requestFullUpdate() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'request_full_update' }));
        }
    }

    sendCommand(type, payload) {
        console.log('[sendCommand] type:', type, 'payload:', payload);
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            const msg = JSON.stringify({ type, ...payload });
            console.log('[sendCommand] sending:', msg);
            this.ws.send(msg);
        } else {
            console.log('[sendCommand] WebSocket not connected');
            toast.error('Not connected to server');
        }
    }

    setupEventListeners() {
        // Keydown listeners
        document.addEventListener('keydown', (e) => {
            if (e.key === 'r' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                this.requestFullUpdate();
            }
            
            if (e.key === 'Escape') {
                closeModal();
                const chartCard = document.getElementById('chartCard');
                if (chartCard && chartCard.classList.contains('fullscreen')) {
                    toggleFullscreen();
                }
            }
        });
        
        // Modal overlay click
        const modalOverlay = document.getElementById('modalOverlay');
        if (modalOverlay) {
            modalOverlay.addEventListener('click', (e) => {
                if (e.target === modalOverlay) {
                    closeModal();
                }
            });
        }
        
        // Target modal overlay click
        const targetModalOverlay = document.getElementById('targetModalOverlay');
        if (targetModalOverlay) {
            targetModalOverlay.addEventListener('click', (e) => {
                if (e.target === targetModalOverlay) {
                    closeTargetModal();
                }
            });
        }
        
        // Target input Enter key handler
        const targetInput = document.getElementById('targetEditInput');
        if (targetInput) {
            targetInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    confirmTargetModal();
                }
                if (e.key === 'Escape') {
                    closeTargetModal();
                }
            });
        }

        // Global click delegation
        document.addEventListener('click', (e) => {
            // Bot commands
            const botCommandBtn = e.target.closest('[data-bot-command]');
            if (botCommandBtn) {
                sendBotCommand(botCommandBtn.dataset.botCommand);
                return;
            }

            // Refresh
            if (e.target.closest('[data-action="refresh"]')) {
                dashboard.sendCommand('bot_command', { command: 'restart' });
                return;
            }

            // Config updates
            const configUpdateBtn = e.target.closest('[data-config-update]');
            if (configUpdateBtn) {
                updateConfig(configUpdateBtn.dataset.configUpdate);
                return;
            }

            // Risk config updates
            const riskConfigUpdateBtn = e.target.closest('[data-config-risk-update]');
            if (riskConfigUpdateBtn) {
                updateRiskConfig(riskConfigUpdateBtn.dataset.configRiskUpdate);
                return;
            }

            // Trading mode toggle
            const modeBtn = e.target.closest('.mode-btn[data-mode]');
            if (modeBtn) {
                setTradingMode(modeBtn.dataset.mode);
                return;
            }

            // Event log clear
            if (e.target.closest('[data-action="clear-events"]')) {
                clearEventLog();
                return;
            }

            // Trade history controls
            if (e.target.closest('[data-action="export-trades"]')) {
                exportTradeHistory();
                return;
            }
            if (e.target.closest('[data-action="clear-trades"]')) {
                clearTradeHistory();
                return;
            }

            // Fullscreen
            if (e.target.closest('[data-action="toggle-fullscreen"]')) {
                toggleFullscreen();
                return;
            }

            // Modal controls
            if (e.target.closest('[data-action="close-modal"]')) {
                closeModal();
                return;
            }
            if (e.target.closest('[data-action="confirm-modal"]')) {
                confirmModal();
                return;
            }
            
            // Target edit modal controls
            if (e.target.closest('[data-action="edit-target"]')) {
                const targetBtn = e.target.closest('[data-action="edit-target"]');
                const targetType = targetBtn.dataset.targetType;
                openTargetModal(targetType);
                return;
            }
            if (e.target.closest('[data-action="close-target-modal"]')) {
                closeTargetModal();
                return;
            }
            if (e.target.closest('[data-action="confirm-target-modal"]')) {
                confirmTargetModal();
                return;
            }

            // Close position
            const closePosBtn = e.target.closest('[data-action="close-position"]');
            if (closePosBtn) {
                closePosition(closePosBtn.dataset.positionId);
                return;
            }

            // Position target button
            const posTargetBtn = e.target.closest('[data-position-target]');
            if (posTargetBtn) {
                const positionId = posTargetBtn.dataset.positionId;
                const currentValue = parseFloat(posTargetBtn.dataset.currentValue);
                showUpdatePositionExitSpreadModal(positionId, currentValue);
                return;
            }

            // Close toast
            const closeToastBtn = e.target.closest('[data-action="close-toast"]');
            if (closeToastBtn) {
                closeToastBtn.parentElement.remove();
                return;
            }
        });

        // Global change delegation
        document.addEventListener('change', (e) => {
            // Event log filter
            if (e.target.closest('[data-action="filter-events"]')) {
                filterEventLog();
                return;
            }

            // Chart range
            if (e.target.closest('[data-action="change-chart-range"]')) {
                changeChartRange();
                return;
            }
        });
    }
}

// Initialize globals
let dashboard = null;
let spreadChart = null;
let toast = null;
let eventLogger = null;
let tradeHistoryManager = null;

document.addEventListener('DOMContentLoaded', () => {
    toast = new ToastNotification();
    eventLogger = new EventLogger();
    tradeHistoryManager = new TradeHistoryManager();
    dashboard = new DashboardClient();
    initSpreadChart();
    
    eventLogger.addEvent('Dashboard initialized', 'success');
});

// Expose for external use
window.dashboard = dashboard;

// Chart initialization with zoom plugin
function initSpreadChart() {
    const ctx = document.getElementById('spreadChart');
    if (!ctx) return;
    
    spreadChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Entry B→H',
                    data: [],
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 4
                },
                {
                    label: 'Entry H→B',
                    data: [],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 4
                },
                {
                    label: 'Exit B→H',
                    data: [],
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 4
                },
                {
                    label: 'Exit H→B',
                    data: [],
                    borderColor: '#f97316',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#9ca3af',
                        usePointStyle: true,
                        pointStyle: 'line',
                        font: { size: 11 }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    titleColor: '#f3f4f6',
                    bodyColor: '#d1d5db',
                    borderColor: '#374151',
                    borderWidth: 1,
                    padding: 10,
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y.toFixed(3)}%`;
                        }
                    }
                },
                zoom: {
                    pan: {
                        enabled: true,
                        mode: 'x'
                    },
                    zoom: {
                        wheel: {
                            enabled: true,
                        },
                        pinch: {
                            enabled: true
                        },
                        mode: 'x',
                    }
                },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            yMin: 0,
                            yMax: 0,
                            borderColor: 'rgba(156, 163, 175, 0.5)',
                            borderWidth: 1,
                            borderDash: [4, 4],
                            label: {
                                display: false
                            }
                        },
                        entryThreshold: {
                            type: 'line',
                            yMin: 0.035,
                            yMax: 0.035,
                            borderColor: 'rgba(34, 197, 94, 0.7)',
                            borderWidth: 2,
                            borderDash: [6, 4],
                            label: {
                                display: true,
                                content: 'Порог входа',
                                position: 'start',
                                backgroundColor: 'rgba(34, 197, 94, 0.8)',
                                color: '#fff',
                                font: { size: 10 }
                            }
                        },
                        exitThreshold: {
                            type: 'line',
                            yMin: 0.006,
                            yMax: 0.006,
                            borderColor: 'rgba(239, 68, 68, 0.7)',
                            borderWidth: 2,
                            borderDash: [6, 4],
                            label: {
                                display: true,
                                content: 'Порог выхода',
                                position: 'end',
                                backgroundColor: 'rgba(239, 68, 68, 0.8)',
                                color: '#fff',
                                font: { size: 10 }
                            }
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: { color: 'rgba(55, 65, 81, 0.3)' },
                    ticks: {
                        color: '#6b7280',
                        maxTicksLimit: 10,
                        font: { size: 10 }
                    }
                },
                y: {
                    display: true,
                    grid: { color: 'rgba(55, 65, 81, 0.3)' },
                    ticks: {
                        color: '#6b7280',
                        callback: function(value) {
                            return value.toFixed(2) + '%';
                        },
                        font: { size: 10 }
                    },
                    min: -1,
                    max: 1
                }
            }
        }
    });
}

function updateSpreadChart(data) {
    if (!spreadChart) return;
    
    const labels = data.labels || [];
    const datasets = data.datasets || {};
    
    spreadChart.data.labels = labels;
    spreadChart.data.datasets[0].data = datasets.entry_bh || [];
    spreadChart.data.datasets[1].data = datasets.entry_hb || [];
    spreadChart.data.datasets[2].data = datasets.exit_bh || [];
    spreadChart.data.datasets[3].data = datasets.exit_hb || [];
    
    spreadChart.update('none');
}

function changeChartRange() {
    if (dashboard && dashboard.requestFullUpdate) {
        dashboard.requestFullUpdate();
    }
}

// Update chart threshold annotations from config
function updateChartThresholds(config) {
    if (!spreadChart || !config) return;
    
    const annotations = spreadChart.options.plugins.annotation.annotations;
    
    if (config.MIN_SPREAD_ENTER !== undefined) {
        const entryThreshold = config.MIN_SPREAD_ENTER * 100;
        annotations.entryThreshold.yMin = entryThreshold;
        annotations.entryThreshold.yMax = entryThreshold;
        annotations.entryThreshold.label.content = `Порог входа (${entryThreshold.toFixed(2)}%)`;
    }
    
    if (config.MIN_SPREAD_EXIT !== undefined) {
        const exitThreshold = config.MIN_SPREAD_EXIT * 100;
        annotations.exitThreshold.yMin = exitThreshold;
        annotations.exitThreshold.yMax = exitThreshold;
        annotations.exitThreshold.label.content = `Порог выхода (${exitThreshold.toFixed(2)}%)`;
    }
    
    spreadChart.update('none');
}

// Reset chart zoom
function resetChartZoom() {
    if (spreadChart) {
        spreadChart.resetZoom();
        eventLogger.addEvent('Зум графика сброшен', 'info');
    }
}

// Update chart Y-axis scale
function updateChartYScale(value) {
    if (!spreadChart) return;
    
    const yAxis = spreadChart.options.scales.y;
    
    if (value === 'auto') {
        yAxis.min = undefined;
        yAxis.max = undefined;
    } else {
        const range = parseFloat(value);
        yAxis.min = -range;
        yAxis.max = range;
    }
    
    spreadChart.update('none');
    eventLogger.addEvent(`Масштаб Y: ±${value}%`, 'info');
}

// Current time aggregation setting
let currentTimeAggMinutes = 1;

// Update chart time aggregation
function updateChartTimeAgg(minutes) {
    currentTimeAggMinutes = parseInt(minutes);
    
    if (dashboard) {
        dashboard.sendCommand('set_time_aggregation', { minutes: currentTimeAggMinutes });
    }
    
    eventLogger.addEvent(`Агрегация: ${minutes} мин`, 'info');
}

// Export spread history to CSV
async function exportToCSV() {
    try {
        const response = await fetch('/api/export-csv');
        if (!response.ok) throw new Error('Ошибка экспорта');
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'spread_history.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        
        eventLogger.addEvent('История экспортирована в CSV', 'success');
        toast.success('История спредов экспортирована');
    } catch (error) {
        console.error('Export error:', error);
        toast.error('Ошибка экспорта CSV');
    }
}

// Fullscreen chart
function toggleFullscreen() {
    const chartCard = document.getElementById('chartCard');
    const btn = document.getElementById('btnFullscreen');
    
    if (!chartCard.classList.contains('fullscreen')) {
        chartCard.classList.add('fullscreen');
        btn.textContent = '🗙 Выход';
        if (spreadChart) {
            spreadChart.resize();
        }
        eventLogger.addEvent('График развёрнут на весь экран', 'success');
    } else {
        chartCard.classList.remove('fullscreen');
        btn.textContent = '🖥️ Полный экран';
        if (spreadChart) {
            spreadChart.resize();
        }
        eventLogger.addEvent('График свёрнут', 'success');
    }
}

// Bot commands
function sendBotCommand(command) {
    const btn = document.getElementById(`btn${command.charAt(0).toUpperCase() + command.slice(1)}`);
    if (btn) {
        btn.disabled = true;
        btn.classList.add('loading');
    }
    
    dashboard.sendCommand('bot_command', { command });
    
    setTimeout(() => {
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('loading');
        }
    }, 2000);
}

// Config updates
function updateConfig(field) {
    let value, payload;
    
    switch (field) {
        case 'min_spread_enter':
            value = parseFloat(document.getElementById('minSpreadEnter').value);
            if (isNaN(value) || value < 0.01 || value > 1.0) {
                toast.error('Min Entry Spread must be between 0.01 and 1.0');
                return;
            }
            payload = { MIN_SPREAD_ENTER: value / 100 };
            break;
        case 'min_spread_exit':
            value = parseFloat(document.getElementById('minSpreadExit').value);
            if (isNaN(value) || value < -1.0 || value > 0.2) {
                toast.error('Min Exit Spread must be between -1.0 and 0.2');
                return;
            }
            payload = { MIN_SPREAD_EXIT: value / 100 };
            break;
        case 'max_position_age':
            value = parseFloat(document.getElementById('maxPositionAge').value);
            if (isNaN(value) || value < 0.5 || value > 24) {
                toast.error('Max Position Age must be between 0.5 and 24 hours');
                return;
            }
            payload = { MAX_POSITION_AGE_HOURS: value };
            break;
        case 'max_concurrent_positions':
            value = parseInt(document.getElementById('maxConcurrentPos').value);
            if (isNaN(value) || value < 1 || value > 10) {
                toast.error('Max Concurrent Positions must be between 1 and 10');
                return;
            }
            payload = { MAX_CONCURRENT_POSITIONS: value };
            break;
        case 'min_order_interval':
            value = parseFloat(document.getElementById('minOrderInterval').value);
            if (isNaN(value) || value < 0 || value > 60) {
                toast.error('Order Interval must be between 0 and 60 seconds');
                return;
            }
            payload = { MIN_ORDER_INTERVAL: value };
            break;
    }
    
    dashboard.sendCommand('update_config', { config: payload });
}

// Risk config updates
function updateRiskConfig(field) {
    let value, payload;
    
    switch (field) {
        case 'daily_loss_limit':
            value = parseFloat(document.getElementById('dailyLossLimit').value);
            if (isNaN(value) || value < 10 || value > 10000) {
                toast.error('Daily Loss Limit must be between 10 and 10000');
                return;
            }
            payload = { DAILY_LOSS_LIMIT: value };
            break;
        case 'max_position_size':
            value = parseFloat(document.getElementById('maxPositionSize').value);
            if (isNaN(value) || value < 0.01 || value > 100) {
                toast.error('Max Position Size must be between 0.01 and 100');
                return;
            }
            payload = { MAX_POSITION_CONTRACTS: value };
            break;
        case 'min_order_contracts':
            value = parseFloat(document.getElementById('minOrderContracts').value);
            if (isNaN(value) || value < 0.001 || value > 10) {
                toast.error('Min Order Size must be between 0.001 and 10');
                return;
            }
            payload = { MIN_ORDER_CONTRACTS: value };
            break;
        case 'max_slippage':
            value = parseFloat(document.getElementById('maxSlippage').value);
            if (isNaN(value) || value < 0.01 || value > 5) {
                toast.error('Max Slippage must be between 0.01 and 5%');
                return;
            }
            payload = { MAX_SLIPPAGE: value / 100 };  // Convert to decimal
            break;
    }
    
    dashboard.sendCommand('update_risk_config', { config: payload });
}

// Trading mode management
let currentTradingMode = 'paper';

function setTradingMode(mode) {
    if (mode === 'live' && currentTradingMode !== 'live') {
        showModal(
            'Включить живую торговлю',
            '⚠️ ВНИМАНИЕ: Вы собираетесь включить ЖИВУЮ ТОРГОВЛЮ.\n\nЭто будет использовать РЕАЛЬНЫЕ ДЕНЬГИ на биржах Hyperliquid и Bitget.\n\nУбедитесь, что вы:\n1. Настроили API-ключи в Secrets\n2. Сначала протестировали на бумажной торговле\n3. Настроили правильные лимиты риска\n\nВы уверены, что хотите продолжить?',
            () => {
                activateTradingMode('live');
            }
        );
    } else if (mode === 'paper') {
        activateTradingMode('paper');
    }
}

function activateTradingMode(mode) {
    currentTradingMode = mode;
    
    document.getElementById('modePaper').classList.toggle('active', mode === 'paper');
    document.getElementById('modeLive').classList.toggle('active', mode === 'live');
    
    const liveWarning = document.getElementById('liveWarning');
    if (liveWarning) {
        liveWarning.style.display = mode === 'live' ? 'block' : 'none';
    }
    
    dashboard.sendCommand('set_trading_mode', { mode: mode });
    
    if (mode === 'live') {
        toast.warning('Live trading mode enabled!');
        eventLogger.addEvent('Switched to LIVE trading mode', 'warning');
    } else {
        toast.success('Paper trading mode enabled');
        eventLogger.addEvent('Switched to Paper trading mode', 'info');
    }
}

function updateApiStatus(status) {
    const hlDot = document.querySelector('#hlStatus .status-dot');
    const bgDot = document.querySelector('#bgStatus .status-dot');
    
    if (hlDot) {
        hlDot.classList.toggle('connected', status.hyperliquid_connected);
        hlDot.classList.toggle('disconnected', !status.hyperliquid_connected);
    }
    
    if (bgDot) {
        bgDot.classList.toggle('connected', status.bitget_connected);
        bgDot.classList.toggle('disconnected', !status.bitget_connected);
    }
}

// Position management
function closePosition(positionId) {
    showModal(
        'Close Position',
        `Are you sure you want to close position #${positionId}?`,
        () => {
            dashboard.sendCommand('close_position', { position_id: positionId });
            eventLogger.addEvent(`Position #${positionId} close requested`, 'warning');
        }
    );
}

function showUpdatePositionExitSpreadModal(positionId, currentValue) {
    showModal(
        'Update Position Exit Target',
        '',
        () => updatePositionExitSpreadFromModal(positionId)
    );

    // Set modal body HTML after showModal
    const modalBody = document.getElementById('modalBody');
    modalBody.innerHTML = `
        <div class="position-modal-content">
            <label>New Exit Target Spread (%)</label>
            <input type="number" id="positionExitSpreadInput" step="0.01" placeholder="0.00" value="${currentValue}" />
        </div>
    `;

    // Set up modal confirm button to call our function
    const confirmBtn = document.getElementById('modalConfirm');
    confirmBtn.onclick = () => {
        updatePositionExitSpreadFromModal(positionId);
    };

    // Focus and select input after modal is visible
    setTimeout(() => {
        const input = document.getElementById('positionExitSpreadInput');
        if (input) {
            input.focus();
            input.select();

            // Add Enter key handler
            input.onkeydown = (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    updatePositionExitSpreadFromModal(positionId);
                }
            };
        }
    }, 100);
}

function updatePositionExitSpreadFromModal(positionId) {
    const input = document.getElementById('positionExitSpreadInput');
    if (!input) return;

    const value = parseFloat(input.value);
    if (isNaN(value)) {
        toast.error('Please enter a valid number');
        return; // Keep modal open
    }

    dashboard.sendCommand('update_position_exit_spread', {
        position_id: positionId,
        new_exit_spread: value
    });

    closeModal();
}

// Trade history
function exportTradeHistory() {
    tradeHistoryManager.exportCSV();
}

function clearTradeHistory() {
    showModal(
        'Clear Trade History',
        'Are you sure you want to clear all trade history? This cannot be undone.',
        () => {
            tradeHistoryManager.clear();
            toast.success('Trade history cleared');
            eventLogger.addEvent('Trade history cleared', 'warning');
        }
    );
}

// Event log
function filterEventLog() {
    const filter = document.getElementById('eventLogFilter').value;
    eventLogger.setFilter(filter);
}

function clearEventLog() {
    showModal(
        'Clear Event Log',
        'Are you sure you want to clear all events?',
        () => {
            eventLogger.clear();
            toast.success('Event log cleared');
        }
    );
}

// Modal functions
function showModal(title, body, onConfirm) {
    const overlay = document.getElementById('modalOverlay');
    const modal = document.getElementById('modal');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');
    
    modalTitle.textContent = title;
    modalBody.textContent = body;
    modalCallback = onConfirm;
    
    overlay.classList.add('active');
}

function closeModal() {
    const overlay = document.getElementById('modalOverlay');
    overlay.classList.remove('active');
    modalCallback = null;
}

function confirmModal() {
    if (modalCallback) {
        modalCallback();
    }
    closeModal();
}

function requestFullUpdate() {
    if (dashboard) {
        dashboard.requestFullUpdate();
        toast.success('Refresh requested');
    }
}

// Target editing functions
function openTargetModal(targetType) {
    const overlay = document.getElementById('targetModalOverlay');
    const input = document.getElementById('targetEditInput');
    const title = document.getElementById('targetModalTitle');
    const description = document.getElementById('targetModalDescription');
    const hint = document.getElementById('targetModalHint');
    
    currentTargetType = targetType;
    
    let currentValue;
    if (targetType === 'entry') {
        const span = document.getElementById('spreadTarget');
        currentValue = parseFloat(span.textContent) || 0.10;
        title.textContent = 'Edit Entry Target';
        description.textContent = 'Enter new entry spread target (minimum required spread):';
        hint.textContent = 'Range: 0.01 - 5.00%';
        input.min = 0.01;
        input.max = 5.00;
        input.step = 0.01;
    } else if (targetType === 'exit') {
        const span = document.getElementById('exitTarget');
        currentValue = parseFloat(span.textContent) || -0.05;
        title.textContent = 'Edit Exit Target';
        description.textContent = 'Enter new exit spread target (position closes when spread >= target):';
        hint.textContent = 'Range: -1.0 - 0.2%';
        input.min = -1.0;
        input.max = 0.2;
        input.step = 0.01;
    }
    
    input.value = currentValue.toFixed(2);
    overlay.classList.add('active');
    
    // Focus and select the input
    setTimeout(() => {
        input.focus();
        input.select();
    }, 100);
}

function closeTargetModal() {
    const overlay = document.getElementById('targetModalOverlay');
    overlay.classList.remove('active');
    currentTargetType = null;
}

function confirmTargetModal() {
    if (!currentTargetType) return;
    
    const input = document.getElementById('targetEditInput');
    const value = parseFloat(input.value);
    
    let payload;
    if (currentTargetType === 'entry') {
        if (isNaN(value) || value < 0.01 || value > 5.00) {
            toast.error('Entry target must be between 0.01 and 5.00%');
            return;
        }
        payload = { MIN_SPREAD_ENTER: value / 100 };
        // Update local display immediately
        document.getElementById('spreadTarget').textContent = value.toFixed(2);
        toast.success(`Entry target updated to ${value.toFixed(2)}%`);
    } else if (currentTargetType === 'exit') {
        if (isNaN(value) || value < -1.0 || value > 0.2) {
            toast.error('Exit target must be between -1.0 and 0.2%');
            return;
        }
        payload = { MIN_SPREAD_EXIT: value / 100 };
        // Update local display immediately
        document.getElementById('exitTarget').textContent = value.toFixed(2);
        toast.success(`Exit target updated to ${value.toFixed(2)}%`);
    }
    
    // Send to server
    dashboard.sendCommand('update_config', { config: payload });
    eventLogger.addEvent(`${currentTargetType.charAt(0).toUpperCase() + currentTargetType.slice(1)} target updated to ${value.toFixed(2)}%`, 'success');
    
    closeTargetModal();
}

// Heatmap functions
async function refreshHeatmap() {
    try {
        const response = await fetch('/api/heatmap');
        if (!response.ok) throw new Error('Ошибка загрузки');
        
        const data = await response.json();
        renderHeatmap(data.heatmap);
    } catch (error) {
        console.error('Heatmap error:', error);
    }
}

function renderHeatmap(heatmapData) {
    const grid = document.getElementById('heatmapGrid');
    if (!grid) return;
    
    grid.innerHTML = '';
    
    let maxSpread = 0;
    for (let hour = 0; hour < 24; hour++) {
        const hourData = heatmapData[hour.toString()] || heatmapData[hour];
        if (hourData && hourData.best_avg > maxSpread) {
            maxSpread = hourData.best_avg;
        }
    }
    
    for (let hour = 0; hour < 24; hour++) {
        const hourData = heatmapData[hour.toString()] || heatmapData[hour] || { best_avg: 0, count: 0 };
        const cell = document.createElement('div');
        cell.className = 'heatmap-cell';
        
        if (hourData.count === 0) {
            cell.classList.add('no-data');
            cell.innerHTML = `<span class="hour">${hour.toString().padStart(2, '0')}</span><span class="value">--</span>`;
        } else {
            const intensity = maxSpread > 0 ? hourData.best_avg / maxSpread : 0;
            const color = getHeatmapColor(intensity);
            cell.style.background = color;
            
            cell.innerHTML = `
                <span class="hour">${hour.toString().padStart(2, '0')}</span>
                <span class="value">${(hourData.best_avg * 100).toFixed(2)}%</span>
                <span class="count">${hourData.count}</span>
            `;
            cell.title = `Час ${hour}:00-${hour}:59\nСр. спред: ${(hourData.best_avg * 100).toFixed(3)}%\nМакс: ${(hourData.max_entry * 100).toFixed(3)}%\nТочек: ${hourData.count}`;
        }
        
        grid.appendChild(cell);
    }
}

function getHeatmapColor(intensity) {
    if (intensity < 0.25) {
        return `rgba(59, 130, 246, ${0.4 + intensity * 0.6})`;
    } else if (intensity < 0.5) {
        return `rgba(16, 185, 129, ${0.5 + intensity * 0.5})`;
    } else if (intensity < 0.75) {
        return `rgba(245, 158, 11, ${0.6 + intensity * 0.4})`;
    } else {
        return `rgba(239, 68, 68, ${0.7 + intensity * 0.3})`;
    }
}

// Clear heatmap statistics
async function clearHeatmapStats() {
    try {
        const response = await fetch('/api/clear-heatmap', { method: 'POST' });
        if (!response.ok) throw new Error('Ошибка очистки');
        
        await refreshHeatmap();
        toast.success('Статистика тепловой карты очищена');
        eventLogger.addEvent('Статистика тепловой карты очищена', 'warning');
    } catch (error) {
        console.error('Clear heatmap error:', error);
        toast.error('Ошибка очистки статистики');
    }
}

setTimeout(() => {
    refreshHeatmap();
}, 2000);
